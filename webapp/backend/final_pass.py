"""FinalTranscriptionPass: authoritative transcription after recording stops.

This module implements the :class:`FinalTranscriptionPass` described in the
design's "Components" section (Task 9.1). It runs the **authoritative** transcription
over the complete recording once a meeting stops, with:

- **Progress reporting** 0..100 via a ``progress_cb`` that is *non-decreasing* and
  reaches 100 on success (Req 2.6, Property 6). The underlying batch service's
  ``transcribe(audio_path, callback)`` reports ``(message, percent)`` pairs; this
  pass adapts them: out-of-range/negative (error-signal) percents are dropped and
  a monotonic clamp ensures values never go backwards even across retries.
- **Retries** up to ``final_pass_max_attempts`` (default from
  :class:`~webapp.backend.models.AppConfig`, i.e. 2). For a transcriber that fails
  ``K`` times before succeeding, the pass performs ``min(K + 1, N)`` attempts and
  declares failure only after exactly ``N`` failed attempts (Req 2.7, Property 7).
- **Failure handling** that *retains* data: this pass is **pure transcription** and
  never deletes the WAV or persisted captions and never writes notes/transcripts
  itself, so on terminal failure both the recording file and the persisted live
  captions still exist and the caller can fall back to the captions (Req 2.8).
- **Model-load abort** (Req 8.6): if the underlying service fails to *load its
  model*, the pass aborts immediately (no point retrying) and surfaces a distinct
  :class:`ModelLoadError` outcome. Because the pass performs **no writes**, "no
  partial notes/transcript writes" holds by construction; persistence belongs to
  ``DocumentService`` / the storage layer.

It also provides the **start-decision** and **transcript-selection** helpers the
session/notes layers need:

- :meth:`should_start` - start a final pass *iff* a non-empty recording exists
  (Req 2.1); otherwise the caller reports the missing-recording condition (Req 2.2).
- :meth:`select_transcript` - prefer the authoritative transcript when present,
  else build one from the persisted live captions; return ``None`` only when
  neither source exists (Req 2.4, 2.5, Property 5).

Dependency injection: the batch-service getter
(:func:`webapp.backend.transcription_registry.get_batch_service`) and
``final_pass_max_attempts`` are injected via the constructor so tests can drive a
``FakeTranscriber`` and arbitrary attempt counts without loading any model.

Integration with :class:`~webapp.backend.session_manager.RecordingSessionManager`
-------------------------------------------------------------------------------

``RecordingSessionManager.stop`` accepts a ``finalizer: callable(StopResult)`` and
only invokes it when a non-empty recording exists. A finalizer built around this
pass (see :class:`FinalizationCoordinator` / :func:`build_finalizer`) would:

1. confirm :meth:`should_start` for the ``StopResult`` (defensive; the manager
   already gates on ``has_recording``);
2. call :meth:`run` with a ``progress_cb`` that broadcasts ``final_progress
   {percent}`` over the WebSocket channel (Req 2.6);
3. on success select the authoritative transcript; on terminal failure fall back
   to the persisted live captions via :meth:`select_transcript` (Req 2.5);
4. broadcast a ``final_result {outcome}`` event (Req 2.3, 2.5, 2.8).

The coordinator deliberately performs **no writes** - persisting the authoritative
transcript is ``DocumentService``'s job - so the model-load "no partial writes"
guarantee is preserved end-to-end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence

from webapp.backend.models import (
    AppConfig,
    Caption,
    StopResult,
    build_transcript_result_from_text,
)

logger = logging.getLogger(__name__)


# Default maximum attempts, mirroring ``AppConfig.final_pass_max_attempts`` (Req 2.7).
DEFAULT_FINAL_PASS_MAX_ATTEMPTS = AppConfig.final_pass_max_attempts  # == 2

# WebSocket event types this layer can broadcast (mirrors the design WS table).
EVENT_FINAL_PROGRESS = "final_progress"
EVENT_FINAL_RESULT = "final_result"
EVENT_MISSING_RECORDING = "missing_recording"

# Final-pass outcomes surfaced to the caller / frontend (Req 2.3, 2.5, 2.8).
OUTCOME_AUTHORITATIVE = "authoritative"
OUTCOME_FALLBACK = "fallback"
OUTCOME_FAILED = "failed"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FinalPassError(RuntimeError):
    """Raised/returned to surface a terminal final-pass failure distinctly.

    Carries the number of attempts performed and the last underlying error so the
    caller can report the failure and fall back to the persisted live captions
    (Req 2.8). Instances are *also* attached to :class:`FinalPassResult.error`;
    callers may either inspect the result's ``success`` flag or catch this type,
    depending on whether they call :meth:`FinalTranscriptionPass.run` (returns a
    result) or :meth:`FinalTranscriptionPass.run_or_raise` (raises).
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 0,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.attempts = attempts
        self.cause = cause
        super().__init__(message)


class ModelLoadError(FinalPassError):
    """Raised/returned when the transcription model fails to load (Req 8.6).

    Distinct from an ordinary transcription failure: retrying will not help, so the
    pass aborts immediately. Because the pass never writes notes/transcripts, no
    partial output is produced. The caller should present a "model could not be
    loaded" error rather than silently falling back.
    """


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class FinalPassResult:
    """The outcome of a :meth:`FinalTranscriptionPass.run` invocation.

    Attributes:
        success: ``True`` iff an authoritative transcript was produced.
        transcript: The authoritative transcript dict on success, else ``None``.
        attempts: How many transcription attempts were performed (including failed
            ones). For a transcriber failing ``K`` times then succeeding under a max
            of ``N`` this is ``min(K + 1, N)`` (Req 2.7); a model-load abort may be
            fewer.
        outcome: ``"authoritative"`` on success, otherwise ``"failed"`` (the caller
            decides between ``"failed"`` and ``"fallback"`` after selecting a
            transcript).
        model_load_failed: ``True`` when the run aborted because the model failed to
            load (Req 8.6).
        error: The terminal :class:`FinalPassError` on failure, else ``None``.
    """

    success: bool
    transcript: Optional[dict] = None
    attempts: int = 0
    outcome: str = OUTCOME_FAILED
    model_load_failed: bool = False
    error: Optional[FinalPassError] = None


@dataclass
class FinalizationResult:
    """The end-to-end result of finalizing a stopped recording.

    Produced by :class:`FinalizationCoordinator`. Captures the transcript actually
    selected for notes generation and where it came from.

    Attributes:
        outcome: ``"authoritative"`` (final pass succeeded), ``"fallback"`` (final
            pass failed but persisted captions were used), or ``"failed"`` (neither
            a transcript nor captions were available).
        transcript: The selected transcript dict for notes input, or ``None``.
        pass_result: The underlying :class:`FinalPassResult` (``None`` when no pass
            was started, e.g. a missing recording).
        started: Whether a final pass was actually started (Req 2.1/2.2).
    """

    outcome: str
    transcript: Optional[dict] = None
    pass_result: Optional[FinalPassResult] = None
    started: bool = False


# ---------------------------------------------------------------------------
# FinalTranscriptionPass
# ---------------------------------------------------------------------------


# Substrings that identify a model-load/download failure in a generic exception's
# message. Used by the default model-load classifier; tests can instead raise
# :class:`ModelLoadError` directly for a deterministic signal.
_MODEL_LOAD_HINTS = (
    "could not load model",
    "failed to load model",
    "unable to load model",
    "model could not be loaded",
    "error loading model",
    "model download failed",
    "failed to download model",
    "unable to download model",
    "could not download model",
    "no such model",
    "model not found",
)


def _default_is_model_load_error(exc: BaseException) -> bool:
    """Default heuristic: is ``exc`` a model-load failure (Req 8.6)?

    Returns ``True`` for our own :class:`ModelLoadError` or for a generic exception
    whose message matches a known model-load/download phrase. Kept conservative so
    ordinary transcription failures still flow through the normal retry path
    (Property 7).
    """
    if isinstance(exc, ModelLoadError):
        return True
    message = str(exc).lower()
    return any(hint in message for hint in _MODEL_LOAD_HINTS)


class FinalTranscriptionPass:
    """Runs the authoritative transcription after stop, with progress + retries.

    The pass is **pure transcription**: it reads the recording and returns/holds the
    transcript. It never deletes the WAV or captions and never writes notes or
    transcripts to disk, so failure handling cannot lose already-produced data
    (Req 2.8) and a model-load abort produces no partial writes (Req 8.6).
    """

    def __init__(
        self,
        *,
        batch_service_getter: Optional[Callable[..., Any]] = None,
        final_pass_max_attempts: int = DEFAULT_FINAL_PASS_MAX_ATTEMPTS,
        is_model_load_error: Optional[Callable[[BaseException], bool]] = None,
    ) -> None:
        """Create a FinalTranscriptionPass.

        Args:
            batch_service_getter: Callable ``(service_id, **kwargs) -> service`` where
                ``service`` exposes ``transcribe(audio_path, callback) -> dict`` and
                the dict conforms to the shared transcript schema. Defaults to
                :func:`webapp.backend.transcription_registry.get_batch_service`.
                Tests inject a getter returning a ``FakeTranscriber``.
            final_pass_max_attempts: Maximum transcription attempts before declaring
                failure (Req 2.7). Clamped to at least 1. Defaults to the
                :class:`AppConfig` default (2).
            is_model_load_error: Optional classifier deciding whether an exception is
                a model-load failure (Req 8.6). Defaults to
                :func:`_default_is_model_load_error`.
        """
        if batch_service_getter is None:
            # Imported lazily so this module imports cleanly and never loads models
            # at import time; the registry's heavy ``transcription`` import is itself
            # deferred until a service is actually constructed.
            from webapp.backend.transcription_registry import get_batch_service

            batch_service_getter = get_batch_service
        self._get_service = batch_service_getter
        self._max_attempts = max(1, int(final_pass_max_attempts))
        self._is_model_load_error = is_model_load_error or _default_is_model_load_error

    @property
    def max_attempts(self) -> int:
        """The configured maximum number of attempts (>= 1)."""
        return self._max_attempts

    # ------------------------------------------------------------------
    # Start decision (Req 2.1, 2.2)
    # ------------------------------------------------------------------

    @staticmethod
    def should_start(stop_result_or_wav: Any) -> bool:
        """Return ``True`` iff a non-empty recording exists to transcribe.

        Accepts either a :class:`~webapp.backend.models.StopResult` (uses its
        ``has_recording`` flag) or a WAV path string (checks the file exists and is
        non-empty). When this returns ``False`` the caller must *not* start a pass
        and should report the missing-recording condition instead (Req 2.1, 2.2,
        Property 4).
        """
        if isinstance(stop_result_or_wav, StopResult):
            return bool(stop_result_or_wav.has_recording)
        return _is_nonempty_file(stop_result_or_wav)

    # ------------------------------------------------------------------
    # Transcript selection (Req 2.4, 2.5)
    # ------------------------------------------------------------------

    @staticmethod
    def select_transcript(
        authoritative: Optional[dict],
        fallback_captions: Optional[Sequence[Any]] = None,
    ) -> Optional[dict]:
        """Select the transcript to feed notes generation (Req 2.4, 2.5, Property 5).

        Prefers ``authoritative`` when present; otherwise builds a transcript from
        the persisted live captions (joining their texts into the shared schema via
        :func:`build_transcript_result_from_text`). Returns ``None`` only when
        neither source exists.

        ``fallback_captions`` may be a sequence of
        :class:`~webapp.backend.models.Caption` objects or plain strings; a present
        but empty-text caption list still counts as an available source and yields a
        (possibly empty) transcript, since at least one source exists.
        """
        if authoritative is not None:
            return authoritative

        captions = list(fallback_captions or [])
        if not captions:
            return None

        text = " ".join(_caption_text(c) for c in captions).strip()
        return build_transcript_result_from_text(text)

    # ------------------------------------------------------------------
    # The run contract (Req 2.6, 2.7, 2.8, 8.6)
    # ------------------------------------------------------------------

    def run(
        self,
        wav_path: str,
        service_id: str,
        progress_cb: Callable[[int], None],
        **service_kwargs: Any,
    ) -> FinalPassResult:
        """Transcribe ``wav_path`` with ``service_id``, retrying up to the max.

        Reports progress 0..100 via ``progress_cb`` - non-decreasing across the
        whole run (including retries) and reaching 100 on success (Req 2.6,
        Property 6). Retries up to ``final_pass_max_attempts`` (Req 2.7, Property 7).

        Returns a :class:`FinalPassResult`:

        * ``success=True`` with the authoritative ``transcript`` on success.
        * ``success=False`` after exactly ``N`` failed attempts; the WAV and any
          persisted captions are untouched (this pass writes nothing), so the caller
          can fall back to the live captions (Req 2.8).
        * ``success=False`` with ``model_load_failed=True`` if the model fails to
          load - the pass aborts immediately without further retries (Req 8.6).

        This method never raises for an ordinary/terminal transcription failure (it
        returns a failure result); construction/programming errors propagate. Use
        :meth:`run_or_raise` if a raising contract is preferred.
        """
        reporter = _MonotonicProgress(progress_cb)
        reporter.report(0)  # establish a starting point within [0, 100]

        last_error: Optional[BaseException] = None
        attempts = 0

        for _ in range(self._max_attempts):
            attempts += 1
            try:
                service = self._get_service(service_id, **service_kwargs)
                result = service.transcribe(wav_path, reporter.on_service_progress)
            except BaseException as exc:  # noqa: BLE001 - we classify & re-wrap below
                if self._is_model_load_error(exc):
                    # Model-load failure: abort immediately, no retry, no writes.
                    logger.error(
                        "Final pass aborted: model failed to load for service %r "
                        "(attempt %d): %s",
                        service_id,
                        attempts,
                        exc,
                    )
                    err = ModelLoadError(
                        f"Transcription model for service {service_id!r} could not "
                        f"be loaded: {exc}",
                        attempts=attempts,
                        cause=exc,
                    )
                    return FinalPassResult(
                        success=False,
                        attempts=attempts,
                        outcome=OUTCOME_FAILED,
                        model_load_failed=True,
                        error=err,
                    )
                last_error = exc
                logger.warning(
                    "Final pass attempt %d/%d failed for service %r: %s",
                    attempts,
                    self._max_attempts,
                    service_id,
                    exc,
                )
                continue

            # Success: ensure the run reaches 100 (Req 2.6) and return.
            reporter.report(100)
            return FinalPassResult(
                success=True,
                transcript=result,
                attempts=attempts,
                outcome=OUTCOME_AUTHORITATIVE,
            )

        # All attempts exhausted: terminal failure. Nothing was written or deleted
        # (Req 2.8); the caller selects the persisted live captions as fallback.
        err = FinalPassError(
            f"Final transcription pass failed after {attempts} attempt(s) for "
            f"service {service_id!r}.",
            attempts=attempts,
            cause=last_error,
        )
        logger.error("%s Last error: %s", err, last_error)
        return FinalPassResult(
            success=False,
            attempts=attempts,
            outcome=OUTCOME_FAILED,
            error=err,
        )

    def run_or_raise(
        self,
        wav_path: str,
        service_id: str,
        progress_cb: Callable[[int], None],
        **service_kwargs: Any,
    ) -> dict:
        """Like :meth:`run` but returns the transcript dict or raises on failure.

        Raises :class:`ModelLoadError` on a model-load abort (Req 8.6) and
        :class:`FinalPassError` on terminal retry failure (Req 2.8). Convenient for
        callers that prefer exception-driven control flow.
        """
        result = self.run(wav_path, service_id, progress_cb, **service_kwargs)
        if result.success and result.transcript is not None:
            return result.transcript
        assert result.error is not None  # invariant: failure carries an error
        raise result.error


# ---------------------------------------------------------------------------
# Monotonic progress adapter (Req 2.6, Property 6)
# ---------------------------------------------------------------------------


class _MonotonicProgress:
    """Adapts service ``(message, percent)`` callbacks into a monotonic 0..100 cb.

    Guarantees every value forwarded to ``progress_cb`` is within ``[0, 100]`` and
    never decreases, even when a retried attempt restarts its own percentage low.
    Negative percents (the existing services' error signal) are dropped rather than
    forwarded as progress.
    """

    def __init__(self, progress_cb: Callable[[int], None]) -> None:
        self._cb = progress_cb
        self._last: int = -1  # nothing reported yet

    def report(self, percent: int) -> None:
        """Forward ``percent`` if it is in-range and >= the last forwarded value."""
        try:
            value = int(percent)
        except (TypeError, ValueError):
            return
        if value < 0:
            return  # error-signal, not a progress value
        if value > 100:
            value = 100
        if value < self._last:
            return  # preserve non-decreasing sequence (Property 6)
        self._last = value
        try:
            self._cb(value)
        except Exception:  # pragma: no cover - progress sink owns its errors
            logger.exception("progress_cb raised; ignoring")

    def on_service_progress(self, message: Any, percent: Any) -> None:
        """Callback matching the services' ``callback(message, percent)`` shape."""
        self.report(percent)


# ---------------------------------------------------------------------------
# Optional finalization seam for RecordingSessionManager (Task 12 wiring helper)
# ---------------------------------------------------------------------------


class FinalizationCoordinator:
    """Ties :class:`FinalTranscriptionPass` + selection + progress broadcasting.

    A lightweight glue object that turns a :class:`StopResult` into a
    :class:`FinalizationResult`, broadcasting ``final_progress``/``final_result``/
    ``missing_recording`` events along the way. It is the natural body of a
    ``RecordingSessionManager`` finalizer.

    **It performs no writes.** Selecting/persisting the authoritative transcript is
    ``DocumentService``'s responsibility; keeping this coordinator write-free
    preserves the model-load "no partial writes" guarantee (Req 8.6) by
    construction.
    """

    def __init__(
        self,
        final_pass: FinalTranscriptionPass,
        service_id: str,
        *,
        captions_provider: Optional[Callable[[Optional[str]], Sequence[Any]]] = None,
        broadcaster: Any = None,
        **service_kwargs: Any,
    ) -> None:
        """Create a coordinator.

        Args:
            final_pass: The :class:`FinalTranscriptionPass` to run.
            service_id: The batch transcription service id to use for the pass.
            captions_provider: Optional ``callable(meeting_id) -> Sequence[Caption]``
                returning the persisted live captions used as the fallback transcript
                source when the pass fails (Req 2.5). When omitted, a failed pass
                yields outcome ``"failed"``.
            broadcaster: Optional event sink - a ``callable(event_type, payload)`` or
                an object exposing ``broadcast(event_type, payload)`` (matching
                ``RecordingSessionManager``'s contract). Used to emit
                ``final_progress`` (Req 2.6), ``final_result`` (Req 2.3/2.5/2.8), and
                ``missing_recording`` (Req 2.2).
            **service_kwargs: Forwarded to the pass / batch-service getter (e.g.
                ``model_size`` for ``whisper``).
        """
        self._pass = final_pass
        self._service_id = service_id
        self._captions_provider = captions_provider
        self._broadcaster = broadcaster
        self._service_kwargs = service_kwargs

    def finalize(self, stop_result: StopResult) -> FinalizationResult:
        """Run the final pass for ``stop_result`` and select the notes transcript.

        Returns a :class:`FinalizationResult`. Emits ``missing_recording`` and does
        not start a pass when no non-empty recording exists (Req 2.1, 2.2). On a
        successful pass the outcome is ``"authoritative"``; on failure it falls back
        to the persisted live captions (``"fallback"``) when any exist, else
        ``"failed"`` (Req 2.5, 2.8).
        """
        meeting_id = getattr(stop_result, "meeting_id", None)
        wav_path = getattr(stop_result, "recording_path", None)

        # Start-decision (Req 2.1/2.2, Property 4).
        if not self._pass.should_start(stop_result):
            self._emit(EVENT_MISSING_RECORDING, {"meeting_id": meeting_id})
            return FinalizationResult(outcome=OUTCOME_FAILED, started=False)

        pass_result = self._pass.run(
            wav_path,
            self._service_id,
            self._on_progress,
            **self._service_kwargs,
        )

        if pass_result.success:
            transcript = FinalTranscriptionPass.select_transcript(
                pass_result.transcript
            )
            self._emit(EVENT_FINAL_RESULT, {"outcome": OUTCOME_AUTHORITATIVE})
            return FinalizationResult(
                outcome=OUTCOME_AUTHORITATIVE,
                transcript=transcript,
                pass_result=pass_result,
                started=True,
            )

        # Terminal failure (incl. model-load abort): fall back to live captions if
        # any were persisted (Req 2.5, 2.8). The WAV + captions remain intact.
        captions = self._load_captions(meeting_id)
        transcript = FinalTranscriptionPass.select_transcript(None, captions)
        outcome = OUTCOME_FALLBACK if transcript is not None else OUTCOME_FAILED
        self._emit(EVENT_FINAL_RESULT, {"outcome": outcome})
        return FinalizationResult(
            outcome=outcome,
            transcript=transcript,
            pass_result=pass_result,
            started=True,
        )

    def _on_progress(self, percent: int) -> None:
        """Broadcast a ``final_progress`` event for each reported percent (Req 2.6)."""
        self._emit(EVENT_FINAL_PROGRESS, {"percent": percent})

    def _load_captions(self, meeting_id: Optional[str]) -> List[Any]:
        """Return persisted live captions for the meeting (best-effort)."""
        if self._captions_provider is None:
            return []
        try:
            return list(self._captions_provider(meeting_id) or [])
        except Exception:  # pragma: no cover - provider owns its errors
            logger.exception("captions_provider failed for meeting %r", meeting_id)
            return []

    def _emit(self, event_type: str, payload: dict) -> None:
        """Best-effort broadcast supporting callable or ``.broadcast`` sinks."""
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


def build_finalizer(
    final_pass: FinalTranscriptionPass,
    service_id: str,
    *,
    captions_provider: Optional[Callable[[Optional[str]], Sequence[Any]]] = None,
    broadcaster: Any = None,
    on_result: Optional[Callable[[FinalizationResult], None]] = None,
    **service_kwargs: Any,
) -> Callable[[StopResult], None]:
    """Build a ``callable(StopResult)`` finalizer for ``RecordingSessionManager``.

    The returned closure runs a :class:`FinalizationCoordinator` for each stop and,
    when provided, hands the :class:`FinalizationResult` to ``on_result`` (e.g. to
    persist the authoritative transcript via ``DocumentService`` - which is the
    *only* place writes should happen). The finalizer itself never writes, keeping
    the model-load "no partial writes" guarantee intact (Req 8.6).
    """
    coordinator = FinalizationCoordinator(
        final_pass,
        service_id,
        captions_provider=captions_provider,
        broadcaster=broadcaster,
        **service_kwargs,
    )

    def _finalize(stop_result: StopResult) -> None:
        result = coordinator.finalize(stop_result)
        if on_result is not None:
            try:
                on_result(result)
            except Exception:  # pragma: no cover - caller owns persistence errors
                logger.exception("on_result callback failed")

    return _finalize


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _is_nonempty_file(path: Any) -> bool:
    """Return ``True`` iff ``path`` names an existing, non-empty file."""
    if not path or not isinstance(path, str):
        return False
    import os

    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:  # pragma: no cover - defensive
        return False


def _caption_text(caption: Any) -> str:
    """Extract text from a :class:`Caption` or a plain string."""
    if isinstance(caption, Caption):
        return caption.text or ""
    if isinstance(caption, str):
        return caption
    text = getattr(caption, "text", None)
    return text if isinstance(text, str) else ""


__all__ = [
    "FinalTranscriptionPass",
    "FinalPassResult",
    "FinalPassError",
    "ModelLoadError",
    "FinalizationCoordinator",
    "FinalizationResult",
    "build_finalizer",
    "DEFAULT_FINAL_PASS_MAX_ATTEMPTS",
    "OUTCOME_AUTHORITATIVE",
    "OUTCOME_FALLBACK",
    "OUTCOME_FAILED",
    "EVENT_FINAL_PROGRESS",
    "EVENT_FINAL_RESULT",
    "EVENT_MISSING_RECORDING",
]
