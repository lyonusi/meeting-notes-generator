"""``LiveTranscriptionEngine`` protocol and ``WhisperLiveEngine`` implementation.

This module is the pluggable *live* transcription seam (Task 6.1). It defines:

- :class:`LiveTranscriptionEngine` - the small ``start``/``feed``/``poll``/``stop``
  protocol every live engine implements. A future AWS Transcribe Streaming engine
  plugs in here with no frontend changes (Req 3.3).
- :class:`WhisperLiveEngine` - a faster-whisper implementation that transcribes
  **rolling, overlapping windows** of an in-memory PCM buffer and classifies the
  produced segments as ``interim`` or ``final`` using a *commit boundary*
  (Req 1.1, 1.2, 1.5, 1.7).

Commit-boundary algorithm (the heart of this module)
-----------------------------------------------------

Audio is fed as raw little-endian 16-bit PCM via :meth:`WhisperLiveEngine.feed`.
The engine never transcribes the whole recording each time; instead, every
``live_window_seconds`` of *new* audio it transcribes a window covering the last
``live_window_seconds + live_overlap_seconds`` seconds of audio::

    window_end    = last_window_end + W          # advances by exactly W each step
    window_start  = max(0, window_end - (W + O)) # = previous commit boundary
    commit_boundary = window_end - O             # final/interim divider

Within a window (segment times converted to absolute recording time):

- A segment whose ``end <= commit_boundary`` is **committed**: emitted once with
  ``status="final"`` (keyed by ``start`` so it is never re-finalized).
- A segment whose ``end > commit_boundary`` lies in the still-mutable *overlap
  tail*: emitted with ``status="interim"`` keyed by ``start``. The next window
  re-transcribes that tail (because ``window_start`` of window N+1 equals the
  commit boundary of window N) and may **revise** the interim text, or promote it
  to ``final`` once the boundary has advanced past it. A ``final`` always
  supersedes an ``interim`` at the same ``start`` (Req 1.7).

On :meth:`WhisperLiveEngine.stop` the remaining mutable tail
(``[commit_boundary, total]``) is transcribed once more and flushed entirely as
``final`` captions.

Latency: an interim caption for audio captured at time *t* is emitted within
roughly ``W`` seconds of capture, and finalized within roughly ``W + O`` seconds
plus the caller's poll interval - comfortably inside the 10s budget (Req 1.5).

faster-whisper is imported **lazily** (only inside :meth:`WhisperLiveEngine._load_model`)
so this module imports cleanly without the model installed, and unit tests can
inject a deterministic ``transcribe_fn`` / fake model without loading anything
(Task 6.2). Models load from the global Hugging Face cache
``~/.cache/huggingface/hub``, downloading on a cache miss (Req 8.4, 8.5).
"""

from __future__ import annotations

import array
import logging
import os
import threading
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)

from webapp.backend.models import Caption

logger = logging.getLogger(__name__)


# A window-relative transcription segment: (start_seconds, end_seconds, text).
Segment = Tuple[float, float, str]

#: A per-window transcription function: given mono float samples in [-1, 1] and
#: their sample rate, return window-relative segments. This is the injectable
#: seam the engine offsets into absolute recording time.
TranscribeFn = Callable[[Sequence[float], int], List[Segment]]

#: Default global Hugging Face hub cache used by faster-whisper (Req 8.4, 8.5).
DEFAULT_HF_CACHE_DIR = os.path.join("~", ".cache", "huggingface", "hub")

#: faster-whisper expects mono float32 audio at this sample rate.
WHISPER_SAMPLE_RATE = 16000

# Default window/overlap mirror ``AppConfig`` defaults (kept in sync there).
DEFAULT_WINDOW_SECONDS = 5.0
DEFAULT_OVERLAP_SECONDS = 2.0


@runtime_checkable
class LiveTranscriptionEngine(Protocol):
    """The pluggable live-transcription seam (Req 3.2, 3.3).

    Implementations consume raw PCM frames as they are captured and produce
    low-latency interim/final :class:`~webapp.backend.models.Caption`s. The
    interface is intentionally tiny so AWS Transcribe Streaming (or any other
    backend) can be added as a new engine with an identical contract and no
    frontend changes.
    """

    #: Stable engine identifier used by ``LiveEngineRegistry`` (e.g. ``"whisper"``).
    id: str

    def start(self, sample_rate: int, channels: int) -> None:
        """Begin a live session for audio of the given format."""
        ...

    def feed(self, pcm_chunk: bytes) -> None:
        """Append raw little-endian 16-bit PCM frames as they are captured."""
        ...

    def poll(self) -> List[Caption]:
        """Return captions produced since the last poll (interim + finalized)."""
        ...

    def stop(self) -> List[Caption]:
        """Flush and return any remaining final captions, ending the session."""
        ...


class WhisperLiveEngine:
    """Rolling/overlapping-window faster-whisper live engine.

    The engine maintains an in-memory PCM buffer of fed audio and transcribes
    overlapping windows, classifying segments as ``interim``/``final`` via a
    commit boundary (see the module docstring for the full algorithm).

    The per-window transcription is injectable for testing: pass ``transcribe_fn``
    (a callable returning window-relative segments) or ``model`` (a preloaded,
    faster-whisper-like object exposing ``transcribe``). When neither is provided,
    faster-whisper is lazily loaded from the global Hugging Face cache on first use.

    Args:
        live_window_seconds: Window stride / commit cadence ``W`` (default 5.0).
        live_overlap_seconds: Mutable overlap tail length ``O`` (default 2.0).
        model_size: faster-whisper model size (default from ``config.WHISPER_MODEL_SIZE``).
        transcribe_fn: Optional injected per-window transcriber (skips model load).
        model: Optional preloaded faster-whisper-like model (skips model load).
        device: faster-whisper device (default ``"cpu"``).
        compute_type: faster-whisper compute type (default ``"int8"``).
        cache_dir: Hugging Face hub cache dir (default ``~/.cache/huggingface/hub``).
        **kwargs: Ignored extra knobs, so ``LiveEngineRegistry`` can call
            ``WhisperLiveEngine(**kwargs)`` with a superset of config values.
    """

    id: str = "whisper"

    def __init__(
        self,
        *,
        live_window_seconds: Optional[float] = None,
        live_overlap_seconds: Optional[float] = None,
        model_size: Optional[str] = None,
        transcribe_fn: Optional[TranscribeFn] = None,
        model: Optional[Any] = None,
        device: str = "cpu",
        compute_type: str = "int8",
        cache_dir: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self._window_seconds = float(
            live_window_seconds
            if live_window_seconds is not None
            else DEFAULT_WINDOW_SECONDS
        )
        self._overlap_seconds = float(
            live_overlap_seconds
            if live_overlap_seconds is not None
            else DEFAULT_OVERLAP_SECONDS
        )
        if self._window_seconds <= 0:
            raise ValueError("live_window_seconds must be > 0")
        if self._overlap_seconds < 0:
            raise ValueError("live_overlap_seconds must be >= 0")

        self._model_size = model_size or _default_model_size()
        self._device = device
        self._compute_type = compute_type
        self._cache_dir = os.path.expanduser(cache_dir or DEFAULT_HF_CACHE_DIR)

        # Injectable seams. ``transcribe_fn`` fully overrides transcription;
        # ``model`` provides a preloaded faster-whisper-like object.
        self._injected_transcribe_fn = transcribe_fn
        self._model = model

        # Audio format (set in ``start``).
        self._sample_rate = WHISPER_SAMPLE_RATE
        self._channels = 1
        self._bytes_per_frame = 2  # int16 mono until ``start`` adjusts channels

        # Mutable session state, guarded by ``_lock``.
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._started = False
        # ``window_end`` of the most recent committed window; windows advance by W.
        self._last_window_end = 0.0
        # Time before which audio is committed (final); advances each window.
        self._commit_boundary = 0.0
        # Finalized captions keyed by ``start`` (never re-finalized / re-emitted).
        self._finalized: Dict[float, Caption] = {}
        # Current interim captions keyed by ``start`` (revisable / supersedable).
        self._interim: Dict[float, Caption] = {}

    # ------------------------------------------------------------------
    # LiveTranscriptionEngine protocol
    # ------------------------------------------------------------------

    def start(self, sample_rate: int, channels: int) -> None:
        """Begin a live session, resetting all per-session state.

        Args:
            sample_rate: PCM sample rate (Hz) of fed audio.
            channels: Number of interleaved channels in fed audio (downmixed to
                mono for transcription).
        """
        if sample_rate <= 0:
            raise ValueError("sample_rate must be > 0")
        if channels <= 0:
            raise ValueError("channels must be > 0")
        with self._lock:
            self._sample_rate = int(sample_rate)
            self._channels = int(channels)
            self._bytes_per_frame = self._channels * 2  # 16-bit samples
            self._buffer = bytearray()
            self._started = True
            self._last_window_end = 0.0
            self._commit_boundary = 0.0
            self._finalized = {}
            self._interim = {}
        logger.info(
            "WhisperLiveEngine started: sr=%d ch=%d window=%.1fs overlap=%.1fs "
            "model=%s",
            self._sample_rate,
            self._channels,
            self._window_seconds,
            self._overlap_seconds,
            self._model_size,
        )

    def feed(self, pcm_chunk: bytes) -> None:
        """Append raw little-endian 16-bit PCM frames to the in-memory buffer."""
        if not pcm_chunk:
            return
        with self._lock:
            if not self._started:
                raise RuntimeError("feed() called before start()")
            self._buffer.extend(pcm_chunk)

    def poll(self) -> List[Caption]:
        """Transcribe any windows that are now due and return their captions.

        Runs zero or more windows so the engine catches up deterministically:
        each window advances ``window_end`` by exactly ``live_window_seconds``.
        Returns the captions emitted across those windows (interim + newly
        finalized), in production order.
        """
        emitted: List[Caption] = []
        while True:
            with self._lock:
                if not self._started:
                    break
                total = self._total_seconds_locked()
                if total - self._last_window_end < self._window_seconds:
                    break
                window_end = self._last_window_end + self._window_seconds
                window_start = max(
                    0.0, window_end - (self._window_seconds + self._overlap_seconds)
                )
                samples = self._extract_region_locked(window_start, window_end)
                self._last_window_end = window_end

            # Transcribe outside the lock (it can be slow) so ``feed`` is not
            # blocked. The extracted ``samples`` are an independent snapshot, and
            # appended audio only grows the buffer tail, so this is safe.
            rel_segments = self._run_transcribe(samples)

            with self._lock:
                if not self._started:
                    break
                emitted.extend(
                    self._classify_locked(window_start, window_end, rel_segments)
                )
        return emitted

    def stop(self) -> List[Caption]:
        """Flush the remaining mutable tail as final captions and end the session.

        Transcribes ``[commit_boundary, total]`` one final time and emits every
        segment there as ``status="final"`` (skipping starts already finalized).
        Leftover interims are cleared. Idempotent: a second call returns ``[]``.
        """
        with self._lock:
            if not self._started:
                return []
            total = self._total_seconds_locked()
            region_start = max(0.0, self._commit_boundary)
            has_audio = bool(self._buffer) and total > region_start
            samples = (
                self._extract_region_locked(region_start, total) if has_audio else []
            )

        emitted: List[Caption] = []
        rel_segments = self._run_transcribe(samples) if samples else []

        with self._lock:
            for rel_start, rel_end, text in rel_segments:
                cap = self._make_caption(region_start, rel_start, rel_end, text, "final")
                if cap is None:
                    continue
                if cap.start in self._finalized:
                    continue
                self._finalized[cap.start] = cap
                self._interim.pop(cap.start, None)
                emitted.append(cap)
            self._interim.clear()
            self._started = False

        logger.info("WhisperLiveEngine stopped: %d final caption(s) flushed", len(emitted))
        return emitted

    # ------------------------------------------------------------------
    # Window classification (commit boundary)
    # ------------------------------------------------------------------

    def _classify_locked(
        self,
        window_start: float,
        window_end: float,
        rel_segments: List[Segment],
    ) -> List[Caption]:
        """Classify window segments into final/interim around the commit boundary.

        Must be called holding ``_lock``. Updates ``_finalized``, ``_interim`` and
        ``_commit_boundary`` and returns the captions to emit for this window.
        """
        commit_boundary = max(window_start, window_end - self._overlap_seconds)
        emitted: List[Caption] = []
        new_interim: Dict[float, Caption] = {}

        for rel_start, rel_end, text in rel_segments:
            if rel_end <= commit_boundary - window_start:
                # Segment ends before the commit boundary -> final.
                cap = self._make_caption(
                    window_start, rel_start, rel_end, text, "final"
                )
                if cap is None:
                    continue
                if cap.start in self._finalized:
                    continue  # already committed in a previous window
                self._finalized[cap.start] = cap
                self._interim.pop(cap.start, None)
                emitted.append(cap)
            else:
                # Segment lies in the mutable overlap tail -> interim (revisable).
                cap = self._make_caption(
                    window_start, rel_start, rel_end, text, "interim"
                )
                if cap is None:
                    continue
                if cap.start in self._finalized:
                    continue  # never downgrade an already-final caption
                new_interim[cap.start] = cap
                emitted.append(cap)

        # Replace the interim set: stale interims from the previous tail that were
        # not reproduced (and not finalized) are dropped.
        self._interim = new_interim
        self._commit_boundary = commit_boundary
        return emitted

    def _make_caption(
        self,
        window_start: float,
        rel_start: float,
        rel_end: float,
        text: str,
        status: str,
    ) -> Optional[Caption]:
        """Build an absolute-time :class:`Caption`, or ``None`` for empty text."""
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        abs_start = round(window_start + float(rel_start), 3)
        abs_end = round(window_start + float(rel_end), 3)
        if abs_end < abs_start:
            abs_end = abs_start
        return Caption(start=abs_start, end=abs_end, text=cleaned, status=status)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # PCM buffer helpers (call holding ``_lock``)
    # ------------------------------------------------------------------

    def _total_seconds_locked(self) -> float:
        """Total buffered duration in seconds (per-channel frames / sample rate)."""
        frames = len(self._buffer) // self._bytes_per_frame
        return frames / float(self._sample_rate)

    def _extract_region_locked(self, start_sec: float, end_sec: float) -> List[float]:
        """Return mono float samples in [-1, 1] for ``[start_sec, end_sec]``.

        Multi-channel audio is downmixed to mono by averaging channels. Returns an
        empty list when the region is empty.
        """
        total_frames = len(self._buffer) // self._bytes_per_frame
        start_frame = max(0, min(total_frames, int(start_sec * self._sample_rate)))
        end_frame = max(0, min(total_frames, int(end_sec * self._sample_rate)))
        if end_frame <= start_frame:
            return []

        byte_start = start_frame * self._bytes_per_frame
        byte_end = end_frame * self._bytes_per_frame
        raw = bytes(self._buffer[byte_start:byte_end])

        samples = array.array("h")  # signed 16-bit
        samples.frombytes(raw)

        if self._channels == 1:
            return [s / 32768.0 for s in samples]

        # Downmix interleaved channels to mono by averaging.
        ch = self._channels
        mono: List[float] = []
        for i in range(0, len(samples), ch):
            frame = samples[i : i + ch]
            if len(frame) < ch:
                break
            mono.append(sum(frame) / (ch * 32768.0))
        return mono

    # ------------------------------------------------------------------
    # Transcription seam (injectable; real model loaded lazily)
    # ------------------------------------------------------------------

    def _run_transcribe(self, samples: Sequence[float]) -> List[Segment]:
        """Run the active per-window transcriber, returning window-relative segments."""
        if not samples:
            return []
        if self._injected_transcribe_fn is not None:
            return list(self._injected_transcribe_fn(samples, self._sample_rate))
        return self._default_transcribe_fn(samples, self._sample_rate)

    def _default_transcribe_fn(
        self, samples: Sequence[float], sample_rate: int
    ) -> List[Segment]:
        """Transcribe ``samples`` with faster-whisper (resampling to 16kHz)."""
        import numpy as np  # lazy: only needed on the real model path

        audio = np.asarray(samples, dtype=np.float32)
        if sample_rate != WHISPER_SAMPLE_RATE and audio.size:
            target_len = int(round(audio.size * WHISPER_SAMPLE_RATE / sample_rate))
            if target_len > 0:
                x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
                x_new = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
                audio = np.interp(x_new, x_old, audio).astype(np.float32)

        model = self._load_model()
        segments, _info = model.transcribe(audio, beam_size=1)
        return [
            (float(seg.start), float(seg.end), str(seg.text))
            for seg in segments
        ]

    def _load_model(self) -> Any:
        """Lazily load and cache the faster-whisper model from the HF hub cache.

        The ``faster_whisper`` import is deferred to here so the module imports
        cleanly without the dependency installed. Models are loaded from / cached
        to ``~/.cache/huggingface/hub`` and downloaded automatically on a cache
        miss (Req 8.4, 8.5).
        """
        if self._model is not None:
            return self._model

        try:
            from faster_whisper import WhisperModel  # noqa: WPS433 (lazy import)
        except ImportError as exc:  # pragma: no cover - exercised only without dep
            raise RuntimeError(
                "faster-whisper is not installed; install 'faster-whisper' to use "
                "the WhisperLiveEngine live path"
            ) from exc

        os.makedirs(self._cache_dir, exist_ok=True)
        logger.info(
            "Loading faster-whisper model %r (device=%s compute_type=%s) from %s",
            self._model_size,
            self._device,
            self._compute_type,
            self._cache_dir,
        )
        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
            download_root=self._cache_dir,
        )
        return self._model


def _default_model_size() -> str:
    """Read the default whisper model size from ``config.py`` (fallback ``small``)."""
    try:
        import config  # the project-root config module

        size = getattr(config, "WHISPER_MODEL_SIZE", None)
        if isinstance(size, str) and size:
            return size
    except Exception:  # pragma: no cover - config import is best-effort
        pass
    return "small"


__all__ = [
    "LiveTranscriptionEngine",
    "WhisperLiveEngine",
    "Segment",
    "TranscribeFn",
    "DEFAULT_HF_CACHE_DIR",
    "WHISPER_SAMPLE_RATE",
]
