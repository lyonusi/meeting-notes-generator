"""RecordingSessionManager: server-side recording state machine.

This module implements the :class:`RecordingSessionManager` described in the
design's "Components" section. It owns **all** server-side recording state for a
single active session (a single local user) and is the single source of truth
shared by the web frontend and (eventually) the tkinter UI.

Scope of this module (Tasks 7.1 + 7.4)
--------------------------------------

* **7.1 - Core state machine.** ``start``/``pause``/``resume``/``stop``/
  ``current``/``list_devices``/``select_device`` enforce the
  ``idle -> recording -> paused -> finalizing`` transitions. An invalid
  transition (e.g. ``pause``/``stop`` when idle) raises a
  :class:`SessionError` with ``reason="invalid_transition"`` and leaves the
  recording state **unchanged** (Req 4.1, 4.7, Property 11). On ``start`` the
  selected input device is validated against the current device list *and* for
  accessibility; on failure the manager stays ``idle``, retains the prior device
  selection, and surfaces a ``reason="device_error"`` failure (Req 4.8, 5.5,
  5.6, Property 13).

* **7.4 - Pause/resume audio + silence classification.** The manager drives the
  existing :class:`audio_capture.AudioRecorder`, which already appends frames
  only while *not* paused, so the saved WAV concatenates exactly the non-paused
  intervals in order (Req 5.7, Property 16). On ``stop`` it reads the recorder's
  ``was_silent`` / ``peak_amplitude`` and assembles a
  :class:`~webapp.backend.models.StopResult` whose ``has_recording`` reflects a
  present, non-empty WAV file (Req 5.8, Property 17).

Reuse, do not reimplement (Req 4.5)
-----------------------------------

Recording, device enumeration, device validation, pause/resume frame handling,
and silence/peak detection all live in :class:`audio_capture.AudioRecorder`.
This manager *orchestrates* that object; it never reimplements capture logic.

Seams left for later tasks
---------------------------

The constructor takes injectable dependencies so this module is testable now and
so later tasks wire real implementations without changing the state machine:

* ``recorder`` / ``recorder_factory`` - the :class:`AudioRecorder` (or a fake in
  tests). Defaults to constructing the real ``AudioRecorder`` lazily so importing
  this module never touches PyAudio.
* ``config_service`` - a :class:`~webapp.backend.config_service.ConfigService`
  used to read/persist the selected input device (Req 5.2).
* ``live_engine`` - an optional :class:`LiveTranscriptionEngine`. Its
  ``start``/``stop`` lifecycle is driven here; the **poll/broadcast loop**
  itself is **Task 8.1** and is intentionally *not* implemented here. The
  ordered, de-duplicated caption snapshot lives on this manager
  (``captions_snapshot`` / :meth:`_ingest_captions`) so Task 8.1 can append to it
  and Task 10.1 can replay it on (re)connect (Req 1.6).
* ``broadcaster`` - an optional event sink (the **Task 10.1** ``WebSocketHub``).
  May be a plain ``callable(event_type, payload)`` or any object exposing a
  ``broadcast(event_type, payload)`` method. All emissions are best-effort and
  guarded, so the state machine works with no hub attached.
* ``finalizer`` - an optional ``callable(StopResult) -> None`` seam for the
  **Task 9.1** ``FinalTranscriptionPass``. When a recording exists, ``stop``
  enters ``finalizing``, invokes the finalizer (if any), then completes back to
  ``idle``. Async drivers can instead set ``auto_finalize=False`` and call
  :meth:`complete_finalization` when the pass finishes.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, List, Optional

from webapp.backend.models import Caption, SessionState, StopResult

logger = logging.getLogger(__name__)


# Event types broadcast over the WebSocket channel (Task 10.1 wires the hub).
# Kept as module constants so the hub and the manager agree on the contract.
EVENT_STATUS = "status"
EVENT_CAPTION = "caption"
EVENT_CHUNK_ERROR = "chunk_error"
EVENT_MISSING_RECORDING = "missing_recording"
EVENT_SILENT_WARNING = "silent_warning"
EVENT_DEVICE_ERROR = "device_error"

# Default cadence of the background poll/broadcast loop (Task 8.1). Tuned well
# under the 10s caption latency budget (Req 1.5) while keeping CPU use modest.
DEFAULT_POLL_INTERVAL_SECONDS = 0.5


class SessionError(Exception):
    """Raised when a session operation is rejected, leaving state unchanged.

    Attributes:
        reason: A stable machine-readable code the API layer (Task 12.1) maps to
            an HTTP status / error envelope. Known values:

            * ``"invalid_transition"`` - the requested transition is not valid
              for the current state (Req 4.7 -> HTTP 409).
            * ``"device_error"`` - the selected input device is missing from the
              current device list or failed accessibility validation
              (Req 4.8, 5.6 -> HTTP 422).
        message: A human-readable explanation suitable for surfacing to the user.
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        self.message = message
        super().__init__(f"[{reason}] {message}")


class RecordingSessionManager:
    """Owns the single server-side recording session and its state machine."""

    #: Valid recording states (mirrors :class:`SessionState` / the design diagram).
    VALID_STATES = ("idle", "recording", "paused", "finalizing")

    def __init__(
        self,
        *,
        recorder: Any = None,
        recorder_factory: Optional[Callable[[], Any]] = None,
        config_service: Any = None,
        live_engine: Any = None,
        broadcaster: Any = None,
        storage: Any = None,
        finalizer: Optional[Callable[[StopResult], None]] = None,
        auto_finalize: bool = True,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        """Create a RecordingSessionManager.

        Args:
            recorder: A pre-built :class:`AudioRecorder` (or compatible fake).
                Takes precedence over ``recorder_factory``.
            recorder_factory: Zero-arg callable returning a recorder; defaults to
                lazily constructing the real :class:`AudioRecorder` only when
                first needed (so importing this module never touches PyAudio).
            config_service: Optional :class:`ConfigService` for reading/persisting
                the selected input device (Req 5.2).
            live_engine: Optional :class:`LiveTranscriptionEngine`; its
                ``start``/``stop`` lifecycle is driven here. The poll/broadcast
                loop is Task 8.1 and is not implemented in this module.
            broadcaster: Optional event sink (Task 10.1 hub). A callable
                ``(event_type, payload)`` or an object with a ``broadcast`` method.
            storage: Optional :class:`StorageManager` used to persist captions on
                stop (Req 2.9). Persistence orchestration belongs to Task 8.1/9.1;
                this manager only calls ``write_captions`` if a store is present.
            finalizer: Optional ``callable(StopResult)`` final-pass seam (Task 9.1).
            auto_finalize: When True (default), ``stop`` completes finalization
                back to ``idle`` synchronously after the finalizer returns. Set
                False for an async final pass that calls
                :meth:`complete_finalization` itself.
            poll_interval: Seconds between background poll-loop iterations (Task
                8.1). Each iteration forwards newly captured audio frames to the
                live engine and pulls/broadcasts any captions it produced.
        """
        self._recorder = recorder
        self._recorder_factory = recorder_factory
        self._config_service = config_service
        self._live_engine = live_engine
        self._broadcaster = broadcaster
        self._storage = storage
        self._finalizer = finalizer
        self._auto_finalize = auto_finalize
        self._poll_interval = float(poll_interval)

        # Re-entrant lock guards all state-machine mutations. Later tasks add a
        # background poll loop (8.1); a single lock keeps state transitions and
        # caption ingestion consistent.
        self._lock = threading.RLock()

        # Session state.
        self._state: str = "idle"
        self._meeting_id: Optional[str] = None
        self._device_id: Optional[int] = None
        self._started_at: Optional[str] = None
        self._final_progress: Optional[int] = None
        self._recording_path: Optional[str] = None

        # Ordered, de-duplicated caption snapshot keyed by ``start`` (Req 1.6).
        # Task 8.1 appends to this from the poll loop; Task 10.1 replays it.
        self._captions: Dict[float, Caption] = {}

        # Registered WS clients (Task 10.1 owns real fan-out; tracked here so
        # ``subscribe`` has a concrete behaviour now).
        self._subscribers: set = set()

        # ---- Background poll/broadcast loop state (Task 8.1) --------------
        # The loop forwards captured audio to the live engine, polls it for
        # captions, ingests them into the snapshot, and emits ``chunk_error`` on
        # a per-window transcription exception (retaining prior captions).
        self._poll_thread: Optional[threading.Thread] = None
        self._poll_stop = threading.Event()
        # Number of recorder ``audio_frames`` already forwarded to the engine, so
        # each newly captured chunk is fed exactly once.
        self._frames_forwarded = 0
        # Monotonic id for chunk-error events (the failing window index).
        self._chunk_counter = 0

    # ------------------------------------------------------------------
    # Recorder access (lazy)
    # ------------------------------------------------------------------

    def _get_recorder(self) -> Any:
        """Return the recorder, constructing it lazily on first use."""
        if self._recorder is None:
            if self._recorder_factory is not None:
                self._recorder = self._recorder_factory()
            else:
                # Imported lazily so this module imports cleanly without PyAudio.
                from audio_capture import AudioRecorder

                self._recorder = AudioRecorder()
        return self._recorder

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def list_devices(self) -> List[Dict[str, Any]]:
        """Return available input devices as ``{"id", "name"}`` dicts (Req 4.2, 5.1).

        Maps the recorder's ``list_devices()["input"]`` ``(index, name)`` tuples
        to lightweight dicts. Returns an empty list when no input devices are
        available (Req 5.1 empty-state).
        """
        recorder = self._get_recorder()
        try:
            inputs = recorder.list_devices().get("input", [])
        except Exception:  # pragma: no cover - defensive; recorder enumerates eagerly
            logger.exception("Failed to enumerate input devices")
            return []
        return [{"id": idx, "name": name} for idx, name in inputs]

    def _input_device_ids(self) -> List[int]:
        """Return the set of currently available input device indices."""
        return [d["id"] for d in self.list_devices()]

    def select_device(self, device_id: Optional[int]) -> None:
        """Persist the selected input device and use it for future recordings (Req 5.2).

        Delegates persistence to :class:`ConfigService` when present (so the
        choice survives restarts) and keeps the recorder in sync. This does not
        validate that the device can capture - that happens at :meth:`start`
        (Req 5.5) - but it does keep the selection until changed.
        """
        with self._lock:
            if self._config_service is not None:
                self._config_service.select_device(device_id)
            if device_id is not None:
                try:
                    self._get_recorder().set_input_device(device_id)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Failed to set recorder input device %r", device_id)

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------

    def current(self) -> SessionState:
        """Return a snapshot of the current :class:`SessionState`."""
        with self._lock:
            return SessionState(
                state=self._state,  # type: ignore[arg-type]
                meeting_id=self._meeting_id,
                device_id=self._device_id,
                duration_seconds=self._current_duration(),
                started_at=self._started_at,
                final_progress=self._final_progress,
            )

    def _current_duration(self) -> float:
        """Best-effort recorded (non-paused) duration via the recorder."""
        if self._state not in ("recording", "paused"):
            return 0.0
        recorder = self._recorder
        if recorder is None:
            return 0.0
        try:
            return float(recorder.get_recording_duration())
        except Exception:  # pragma: no cover - defensive
            return 0.0

    def captions_snapshot(self) -> List[Caption]:
        """Return all captions produced so far, ascending by ``start`` (Req 1.6).

        This is the replay buffer Task 10.1's hub sends to a client on
        (re)connect before streaming live events.
        """
        with self._lock:
            return [self._captions[k] for k in sorted(self._captions)]

    def subscribe(self, ws: Any) -> None:
        """Register a WebSocket client (Task 10.1 owns real fan-out).

        Tracks the client and, when a broadcaster/hub exposing ``subscribe`` is
        injected, delegates to it. Kept minimal here; the on-connect caption
        replay is driven via :meth:`captions_snapshot`.
        """
        with self._lock:
            self._subscribers.add(ws)
        hub = self._broadcaster
        if hub is not None and hasattr(hub, "subscribe"):
            try:
                hub.subscribe(ws)
            except Exception:  # pragma: no cover - defensive
                logger.exception("broadcaster.subscribe failed")

    # ------------------------------------------------------------------
    # State machine: start / pause / resume / stop
    # ------------------------------------------------------------------

    def start(self, device_id: Optional[int] = None) -> SessionState:
        """Start a recording from ``idle`` (Req 4.1, 5.5, 5.6, 4.8; Property 13).

        Resolves the device to use (explicit ``device_id`` if given, else the
        persisted/selected device), validates it is present in the current
        device list **and** passes accessibility validation, then begins capture.

        Raises:
            SessionError(reason="invalid_transition"): if not currently ``idle``.
            SessionError(reason="device_error"): if the device is missing or
                fails validation. The state remains ``idle`` and the previous
                device selection is retained (Req 5.6); a ``device_error`` event
                is emitted for the frontend.
        """
        with self._lock:
            self._require_state("start", {"idle"})

            recorder = self._get_recorder()
            resolved_id = self._resolve_device_id(device_id)

            # (a) Membership in the current device list (Req 4.8, 5.5).
            available = self._input_device_ids()
            if resolved_id is None or resolved_id not in available:
                msg = (
                    f"Selected input device {resolved_id!r} is not in the list of "
                    f"available input devices."
                )
                self._emit(EVENT_DEVICE_ERROR, {"message": msg})
                # Stay idle; retain prior selection (we never mutated it).
                raise SessionError("device_error", msg)

            # (b) Accessibility validation (Req 5.5). The recorder does the real
            # check (channels + format support); we do not reimplement it.
            ok, reason = recorder.validate_input_device(resolved_id)
            if not ok:
                self._emit(EVENT_DEVICE_ERROR, {"message": reason})
                raise SessionError("device_error", reason)

            # Device is valid: point the recorder at it and begin capture.
            recorder.set_input_device(resolved_id)
            started = recorder.start_recording()
            if not started:
                # The recorder rejected the start (e.g. a late device failure);
                # surface its reason and remain idle.
                reason = getattr(recorder, "last_error", None) or (
                    "Recording failed to start."
                )
                self._emit(EVENT_DEVICE_ERROR, {"message": reason})
                raise SessionError("device_error", reason)

            # Transition idle -> recording and capture session identity.
            self._device_id = resolved_id
            self._meeting_id = self._derive_meeting_id(
                getattr(recorder, "recording_filename", None)
            )
            self._recording_path = getattr(recorder, "recording_filename", None)
            self._started_at = self._now_iso()
            self._final_progress = None
            self._captions = {}
            self._set_state("recording")

            # Drive the live engine lifecycle (the poll/broadcast loop is Task 8.1).
            self._start_live_engine(recorder)

            return self.current()

    def pause(self) -> SessionState:
        """Pause an in-progress recording: ``recording -> paused`` (Req 4.1, 4.7).

        Raises SessionError(reason="invalid_transition") from any other state,
        leaving the state unchanged (Property 11).
        """
        with self._lock:
            self._require_state("pause", {"recording"})
            recorder = self._get_recorder()
            recorder.pause_recording()
            self._set_state("paused")
            return self.current()

    def resume(self) -> SessionState:
        """Resume a paused recording: ``paused -> recording`` (Req 4.1, 5.7).

        The recorder appends post-resume audio to the same recording, so the
        saved WAV is the in-order concatenation of the non-paused intervals
        (Req 5.7, Property 16). Raises SessionError(reason="invalid_transition")
        from any other state, leaving the state unchanged.
        """
        with self._lock:
            self._require_state("resume", {"paused"})
            recorder = self._get_recorder()
            # AudioRecorder.start_recording() clears the paused flag and resumes
            # appending to the same audio_frames buffer (Req 5.7).
            recorder.start_recording()
            self._set_state("recording")
            return self.current()

    def stop(self) -> StopResult:
        """Stop recording and assemble a :class:`StopResult` (Req 4.1, 2.1, 2.2, 5.8).

        Allowed from ``recording`` or ``paused``. Stops the recorder, flushes the
        live engine, persists captions (if a store is injected), and:

        * If a non-empty WAV exists: enters ``finalizing`` (the final-pass seam,
          Task 9.1), invokes the injected ``finalizer`` if any, then - when
          ``auto_finalize`` is True - completes back to ``idle``.
        * If no/empty WAV exists: returns to ``idle`` and emits a
          ``missing_recording`` event (Req 2.2).

        Also emits a ``silent_warning`` event when the recorder classified the
        audio as silent (Req 5.8).

        Raises SessionError(reason="invalid_transition") from ``idle`` /
        ``finalizing``, leaving the state unchanged (Property 11).
        """
        with self._lock:
            self._require_state("stop", {"recording", "paused"})

            recorder = self._get_recorder()
            meeting_id = self._meeting_id

            # Stop capture; AudioRecorder saves the concatenated non-paused frames
            # and returns the WAV path (or None when nothing was captured).
            path = recorder.stop_recording()

            # Flush the live engine's remaining final captions into the snapshot
            # (the continuous poll loop is Task 8.1).
            self._stop_live_engine()

            has_recording = self._is_nonempty_file(path)
            was_silent = bool(getattr(recorder, "was_silent", False))
            peak_amplitude = int(getattr(recorder, "peak_amplitude", 0) or 0)

            result = StopResult(
                meeting_id=meeting_id,
                recording_path=path if has_recording else None,
                has_recording=has_recording,
                was_silent=was_silent,
                peak_amplitude=peak_amplitude,
            )

            # Persist captions for fallback/replay (Req 2.9) when a store is wired.
            self._persist_captions(meeting_id)

            if not has_recording:
                # recording -> idle with a missing-recording report (Req 2.2).
                self._emit(EVENT_MISSING_RECORDING, {"meeting_id": meeting_id})
                self._reset_session()
                self._set_state("idle")
                return result

            # Non-empty recording: enter finalizing (final-pass seam, Task 9.1).
            if was_silent:
                self._emit(
                    EVENT_SILENT_WARNING,
                    {"meeting_id": meeting_id, "peak_amplitude": peak_amplitude},
                )
            self._recording_path = path
            self._final_progress = 0
            self._set_state("finalizing")

        # Invoke the final-pass seam outside the lock (it can be slow and may
        # itself report progress/broadcast). Task 9.1 provides the real pass.
        if self._finalizer is not None:
            try:
                self._finalizer(result)
            except Exception:  # pragma: no cover - finalizer owns its errors
                logger.exception("finalizer raised for meeting %r", meeting_id)

        if self._auto_finalize:
            self.complete_finalization()

        return result

    def complete_finalization(self) -> SessionState:
        """Complete the final pass: ``finalizing -> idle`` (design state diagram).

        Idempotent: a no-op when not currently ``finalizing``. Exposed so an
        async final pass (Task 9.1) can signal completion explicitly when
        ``auto_finalize`` is disabled.
        """
        with self._lock:
            if self._state != "finalizing":
                return self.current()
            self._reset_session()
            self._set_state("idle")
            return self.current()

    # ------------------------------------------------------------------
    # Live-engine lifecycle (poll/broadcast loop is Task 8.1)
    # ------------------------------------------------------------------

    def _start_live_engine(self, recorder: Any) -> None:
        """Start the live engine for this session and launch the poll loop (Task 8.1)."""
        if self._live_engine is None:
            return
        try:
            from config import CHANNELS, RATE

            channels = getattr(recorder, "_channels_used", None) or CHANNELS
            self._live_engine.start(RATE, channels)
        except Exception:  # pragma: no cover - defensive; engine is optional
            logger.exception("live engine start() failed")
            return

        # Spin up the background poll/broadcast loop. Reset per-session counters
        # so a new recording forwards frames from the start and chunk ids restart.
        self._frames_forwarded = 0
        self._chunk_counter = 0
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="session-poll-loop",
            daemon=True,
        )
        self._poll_thread.start()

    def _stop_poll_loop(self) -> None:
        """Signal the poll loop to exit and join it (cleanly, off the lock)."""
        thread = self._poll_thread
        if thread is None:
            return
        self._poll_stop.set()
        # Never join from within the loop's own thread; guard defensively.
        if thread is not threading.current_thread():
            thread.join(timeout=max(2.0, self._poll_interval * 4))
        self._poll_thread = None

    def _poll_loop(self) -> None:
        """Forward captured audio to the engine and broadcast produced captions.

        Runs on a daemon thread for the lifetime of a recording (Task 8.1):

        1. Forward any newly captured recorder ``audio_frames`` to the engine via
           ``feed`` (tracking how many frames were already forwarded so each chunk
           is fed exactly once). Pausing simply means no new frames appear, so the
           loop idles without error (Req 5.7).
        2. Poll the engine for captions and ingest them into the ordered,
           de-duplicated snapshot, broadcasting each as a ``caption`` event
           (Req 1.3, 1.6).
        3. If ``poll`` raises (a per-window transcription failure), emit a
           ``chunk_error{chunk_id}`` event, keep the existing snapshot intact, and
           continue with subsequent windows (Req 1.8).
        """
        engine = self._live_engine
        while not self._poll_stop.is_set():
            try:
                self._forward_new_frames(engine)
                captions = engine.poll()
            except Exception:  # per-window transcription failure (Req 1.8)
                self._chunk_counter += 1
                logger.exception(
                    "live engine poll failed for chunk %d; retaining prior "
                    "captions and continuing",
                    self._chunk_counter,
                )
                self._emit(
                    EVENT_CHUNK_ERROR,
                    {
                        "chunk_id": self._chunk_counter,
                        "message": "A transcription window failed; continuing.",
                    },
                )
            else:
                if captions:
                    self._ingest_captions(captions)
            self._poll_stop.wait(self._poll_interval)

    def _forward_new_frames(self, engine: Any) -> None:
        """Feed recorder ``audio_frames`` captured since the last forward to the engine.

        ``AudioRecorder`` appends one raw int16 PCM byte chunk per read to
        ``audio_frames``; we forward each newly appended chunk exactly once via
        ``engine.feed`` and remember how many we have sent. A snapshot of the list
        is taken before slicing so concurrent appends from the recorder thread are
        safe (the list only grows at the tail).
        """
        recorder = self._recorder
        if recorder is None:
            return
        frames = getattr(recorder, "audio_frames", None)
        if not frames:
            return
        # Snapshot the current length; new appends past this point are picked up
        # on the next iteration.
        available = len(frames)
        if available <= self._frames_forwarded:
            return
        new_chunks = frames[self._frames_forwarded:available]
        for chunk in new_chunks:
            if chunk:
                engine.feed(chunk)
        self._frames_forwarded = available

    def _stop_live_engine(self) -> None:
        """Stop the poll loop, then flush the engine's final captions (Task 8.1)."""
        if self._live_engine is None:
            return
        # Stop the background loop first so no concurrent poll races the flush.
        self._stop_poll_loop()
        # Forward any audio captured after the last loop iteration before flushing
        # so the final window covers the full recording.
        try:
            self._forward_new_frames(self._live_engine)
        except Exception:  # pragma: no cover - best-effort final feed
            logger.exception("final audio forward before flush failed")
        try:
            final_caps = self._live_engine.stop()
        except Exception:  # pragma: no cover - defensive
            logger.exception("live engine stop() failed")
            return
        if final_caps:
            self._ingest_captions(final_caps)

    def _ingest_captions(self, captions: List[Caption]) -> None:
        """Merge captions into the ordered, de-duplicated snapshot keyed by ``start``.

        This is the hook Task 8.1's poll loop uses to append captions; a ``final``
        caption supersedes an ``interim`` at the same ``start`` (Req 1.7). Each
        ingested caption is also broadcast for live clients.
        """
        with self._lock:
            for cap in captions:
                self._captions[cap.start] = cap
        for cap in captions:
            self._emit(
                EVENT_CAPTION,
                {
                    "text": cap.text,
                    "start": cap.start,
                    "end": cap.end,
                    "status": cap.status,
                },
            )

    def _persist_captions(self, meeting_id: Optional[str]) -> None:
        """Persist the caption snapshot via the storage seam (Req 2.9), if wired."""
        if self._storage is None or meeting_id is None:
            return
        try:
            self._storage.write_captions(meeting_id, self.captions_snapshot())
        except Exception:  # pragma: no cover - persistence is best-effort here
            logger.exception("Failed to persist captions for meeting %r", meeting_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_state(self, action: str, allowed: set) -> None:
        """Raise an invalid-transition error unless the current state is allowed."""
        if self._state not in allowed:
            raise SessionError(
                "invalid_transition",
                f"Cannot {action} while {self._state!r}; "
                f"valid only from {sorted(allowed)}.",
            )

    def _set_state(self, new_state: str) -> None:
        """Set the recording state and broadcast a status update (Req 4.4)."""
        assert new_state in self.VALID_STATES, new_state
        self._state = new_state
        self._emit(
            EVENT_STATUS,
            {"state": new_state, "duration": self._current_duration()},
        )

    def _reset_session(self) -> None:
        """Clear per-session identity fields (called when returning to idle)."""
        self._meeting_id = None
        self._device_id = None
        self._started_at = None
        self._final_progress = None
        self._recording_path = None

    def _resolve_device_id(self, device_id: Optional[int]) -> Optional[int]:
        """Resolve the device to start with: explicit arg, else selected/default."""
        if device_id is not None:
            return device_id
        # Prefer the persisted selection from ConfigService (Req 5.2).
        if self._config_service is not None:
            try:
                cfg = self._config_service.get()
                if getattr(cfg, "input_device_id", None) is not None:
                    return cfg.input_device_id
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to read selected device from config")
        # Fall back to the recorder's current input device.
        recorder = self._get_recorder()
        try:
            return recorder.device_info.get("input")
        except Exception:  # pragma: no cover - defensive
            return None

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Best-effort broadcast to the injected sink (Task 10.1 hub), if any."""
        hub = self._broadcaster
        if hub is None:
            return
        try:
            if hasattr(hub, "broadcast"):
                hub.broadcast(event_type, payload)
            elif callable(hub):
                hub(event_type, payload)
        except Exception:  # pragma: no cover - broadcasting is best-effort
            logger.exception("broadcast of %r failed", event_type)

    @staticmethod
    def _is_nonempty_file(path: Optional[str]) -> bool:
        """Return True iff ``path`` exists and is a non-empty file (Req 2.1/2.2)."""
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0

    @staticmethod
    def _derive_meeting_id(recording_filename: Optional[str]) -> Optional[str]:
        """Derive the ``YYYYMMDD_HHMMSS`` meeting id from the recording filename.

        ``AudioRecorder`` names files ``meeting_{timestamp}.wav``; the meeting id
        is that timestamp so :class:`StopResult` and the recording path agree.
        """
        if not recording_filename:
            return None
        base = os.path.basename(recording_filename)
        stem, _ext = os.path.splitext(base)
        if stem.startswith("meeting_"):
            return stem[len("meeting_"):]
        return stem

    @staticmethod
    def _now_iso() -> str:
        """Return the current local time as an ISO-8601 string."""
        from datetime import datetime

        return datetime.now().isoformat()


__all__ = [
    "RecordingSessionManager",
    "SessionError",
    "EVENT_STATUS",
    "EVENT_CAPTION",
    "EVENT_CHUNK_ERROR",
    "EVENT_MISSING_RECORDING",
    "EVENT_SILENT_WARNING",
    "EVENT_DEVICE_ERROR",
]
