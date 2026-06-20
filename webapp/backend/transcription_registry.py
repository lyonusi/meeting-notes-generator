"""Pluggable transcription seam: batch service adapter + ``LiveEngineRegistry``.

This module is the single choke point through which transcription engines are
selected *by id* (Task 5.1). It does two related things:

1. **Batch services** (the Final_Transcription_Pass path). It wraps the existing
   :class:`transcription.TranscriptionService` factory (``whisper``/``aws``/``mac``)
   behind one small interface so every service is requested by id and returns the
   shared AWS-Transcribe-compatible ``TranscriptResult`` shape
   (``results.transcripts[0].transcript`` is a ``str``). The existing logic is
   *reused, never reimplemented* (Req 4.5): ``whisper``/``mac`` delegate to the
   service's ``transcribe(audio_file_path, callback=None)`` method, and ``aws``
   wraps :class:`aws_services.AWSHandler`'s two-step
   ``upload_audio_to_s3`` + ``transcribe_audio`` flow into the same one-call
   interface.

2. **Live engines** (the low-latency live caption path). :class:`LiveEngineRegistry`
   maps an engine id to a factory callable. ``whisper`` is registered with a
   *lazy* factory that imports :class:`webapp.backend.live_engine.WhisperLiveEngine`
   only at construction time, so the registry mechanism works now and the engine
   (Task 6.1) slots in later with no change here. ``aws-streaming`` is registered
   as a documented placeholder for the future AWS Transcribe Streaming seam
   (Req 3.3) -- the registry knows about the id but constructing it raises a clear
   "not implemented" error.

Unknown ids are rejected with a clear error for both registries
(:class:`UnknownServiceError`) *before any state is mutated*, so requesting an
unregistered service leaves the currently active service unchanged (Req 3.5,
Property 10). :class:`BatchServiceRegistry` provides an explicit ``active``
service slot to make that invariant concrete and testable.

Relevant requirements: 3.1 (shared interface/shape), 3.2 (request by id), 3.3
(new id selectable with no frontend change / future streaming seam), 3.4
(``whisper``/``aws``/``mac`` for the final pass), 3.5 (unknown id rejected,
active service retained).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from webapp.backend.models import validate_transcript_result

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known ids and errors
# ---------------------------------------------------------------------------

#: Batch transcription service ids reused from ``transcription.TranscriptionService``.
KNOWN_BATCH_SERVICE_IDS: tuple[str, ...] = ("whisper", "aws", "mac")

#: Live engine ids that are *documented* but not yet implemented. These are the
#: future-seam placeholders (Req 3.3). Looking them up reports a clear
#: "not implemented" error rather than an "unknown id" error.
LIVE_PLACEHOLDER_DOCS: Dict[str, str] = {
    "aws-streaming": (
        "AWS Transcribe Streaming live engine. Documented future seam: a new "
        "LiveTranscriptionEngine implementation registered under this id will "
        "plug in here with no frontend changes (Req 3.3). Not yet implemented."
    ),
}


class UnknownServiceError(ValueError):
    """Raised when a transcription engine is requested by an unregistered id.

    Subclasses :class:`ValueError` for parity with the existing
    ``transcription.TranscriptionService.get_service`` behaviour, while remaining
    catchable as a distinct type. Raising this never mutates any registry or
    active-service state (Req 3.5).
    """

    def __init__(self, service_id: Any, known_ids: Any) -> None:
        self.service_id = service_id
        self.known_ids = tuple(known_ids)
        known = ", ".join(str(k) for k in self.known_ids) or "(none)"
        super().__init__(
            f"Unknown transcription service id {service_id!r}; known ids: {known}"
        )


class UnimplementedEngineError(NotImplementedError):
    """Raised when a *documented but unimplemented* engine id is constructed.

    Distinct from :class:`UnknownServiceError`: the id is a known future seam
    (e.g. ``aws-streaming``) that has been reserved/documented but not built yet.
    """

    def __init__(self, engine_id: Any, doc: Optional[str] = None) -> None:
        self.engine_id = engine_id
        self.doc = doc
        message = f"Transcription engine {engine_id!r} is a documented placeholder " \
                  f"that is not yet implemented."
        if doc:
            message = f"{message} {doc}"
        super().__init__(message)


# ---------------------------------------------------------------------------
# Batch transcription adapter
# ---------------------------------------------------------------------------


@runtime_checkable
class BatchTranscriber(Protocol):
    """The small batch interface: ``transcribe(audio_path, callback) -> dict``.

    ``callback`` (when provided) is invoked with ``(message, percent)`` pairs and
    the returned dict conforms to the shared transcript schema (Req 3.1).
    """

    id: str

    def transcribe(
        self,
        audio_path: str,
        callback: Optional[Callable[[str, int], None]] = None,
    ) -> dict: ...


class BatchTranscriptionService:
    """Uniform ``transcribe(audio_path, callback)`` adapter over an existing service.

    Wraps an instance produced by ``transcription.TranscriptionService.get_service``
    so all batch services are driven through one interface (Req 3.1, 3.4):

    - ``whisper`` / ``mac`` delegate straight to the underlying service's
      ``transcribe(audio_file_path, callback)``.
    - ``aws`` wraps :class:`aws_services.AWSHandler`'s two-step
      ``upload_audio_to_s3`` -> ``transcribe_audio`` flow into a single call,
      matching the orchestration the existing tkinter/notes path performs.

    The result is validated against the shared schema so callers can rely on
    ``results.transcripts[0].transcript`` being a ``str`` regardless of the
    backing implementation (Req 3.1).
    """

    def __init__(self, service_id: str, underlying: Any, *, is_aws: bool = False) -> None:
        self.id = service_id
        self._underlying = underlying
        self._is_aws = is_aws

    @property
    def underlying(self) -> Any:
        """The wrapped service instance (e.g. ``WhisperTranscription``/``AWSHandler``)."""
        return self._underlying

    def transcribe(
        self,
        audio_path: str,
        callback: Optional[Callable[[str, int], None]] = None,
    ) -> dict:
        """Transcribe ``audio_path`` and return a shared-shape transcript dict.

        Raises whatever the underlying service raises on failure (so a dependency
        that is unavailable surfaces its error and no partial transcript is
        returned -- Req 3.6). The returned dict is validated to conform to the
        shared transcript schema (Req 3.1).
        """
        if self._is_aws:
            result = self._transcribe_aws(audio_path, callback)
        else:
            result = self._underlying.transcribe(audio_path, callback)

        if result is None:
            # A None result means the underlying transcription did not produce a
            # transcript (e.g. an AWS job that failed). Surface a clear failure
            # rather than returning a partial/empty transcript (Req 3.6).
            raise RuntimeError(
                f"Transcription service {self.id!r} returned no transcript for "
                f"{audio_path!r}"
            )

        # Conformance to the shared shape (Req 3.1). Raises TranscriptResultError
        # (a ValueError) if the structure is wrong.
        validate_transcript_result(result)
        return result

    def _transcribe_aws(
        self,
        audio_path: str,
        callback: Optional[Callable[[str, int], None]],
    ) -> Optional[dict]:
        """Run the existing AWS two-step flow behind the unified interface.

        Reuses :class:`aws_services.AWSHandler` exactly as the existing
        notes/tkinter path does: upload the audio to S3, then start/await the
        Transcribe job. No transcription logic is reimplemented here (Req 4.5).
        """
        handler = self._underlying
        if callback:
            callback("Uploading audio to S3...", 10)
        s3_uri = handler.upload_audio_to_s3(audio_path)
        if callback:
            callback("Transcribing audio with AWS Transcribe...", 30)
        result = handler.transcribe_audio(s3_uri)
        if callback:
            callback("Transcription complete!", 100)
        return result


def require_known_batch_service(service_id: str) -> None:
    """Validate ``service_id`` is a known batch service or raise.

    Raises :class:`UnknownServiceError` *without any side effect* so callers can
    use it as a guard that leaves active state untouched (Req 3.5).
    """
    if service_id not in KNOWN_BATCH_SERVICE_IDS:
        raise UnknownServiceError(service_id, KNOWN_BATCH_SERVICE_IDS)


def get_batch_service(service_id: str, **kwargs: Any) -> BatchTranscriptionService:
    """Return a :class:`BatchTranscriptionService` for ``service_id``.

    ``service_id`` must be one of :data:`KNOWN_BATCH_SERVICE_IDS`
    (``whisper``/``aws``/``mac``); any other id raises
    :class:`UnknownServiceError` before constructing anything (Req 3.5).

    ``**kwargs`` are forwarded to the existing factory, e.g.
    ``get_batch_service("whisper", model_size="base")`` or
    ``get_batch_service("aws", bedrock_profile="bedrock")``. Constructing the
    ``whisper`` service does *not* load the model (the model is lazy-loaded on
    the first ``transcribe`` call), so the factory dispatch is cheap to exercise.
    """
    # Validate id first so an unknown id never triggers construction/side effects.
    require_known_batch_service(service_id)

    # Import lazily to keep this module importable without the heavy deps and to
    # reuse the single existing factory (Req 4.5).
    from transcription import TranscriptionService

    underlying = TranscriptionService.get_service(service_id, **kwargs)
    return BatchTranscriptionService(
        service_id, underlying, is_aws=(service_id == "aws")
    )


class BatchServiceRegistry:
    """Stateful selector for batch services with an explicit ``active`` slot.

    The registry holds the currently active batch service. Selecting a known id
    constructs the adapter and updates the active slot; selecting an *unknown* id
    raises :class:`UnknownServiceError` and leaves the active service unchanged
    (Req 3.5, Property 10). This makes the "retain active service on rejection"
    invariant concrete and testable.
    """

    def __init__(
        self,
        factory: Callable[..., BatchTranscriptionService] = get_batch_service,
    ) -> None:
        self._factory = factory
        self._active_id: Optional[str] = None
        self._active_service: Optional[BatchTranscriptionService] = None

    @property
    def available(self) -> List[str]:
        """The selectable batch service ids."""
        return list(KNOWN_BATCH_SERVICE_IDS)

    @property
    def active_id(self) -> Optional[str]:
        """The id of the currently active service, or ``None`` if none selected."""
        return self._active_id

    @property
    def active_service(self) -> Optional[BatchTranscriptionService]:
        """The currently active service instance, or ``None`` if none selected."""
        return self._active_service

    def is_registered(self, service_id: str) -> bool:
        """Return whether ``service_id`` is a known batch service id."""
        return service_id in KNOWN_BATCH_SERVICE_IDS

    def select(self, service_id: str, **kwargs: Any) -> BatchTranscriptionService:
        """Select and activate the service for ``service_id``.

        On an unknown id this raises :class:`UnknownServiceError` *before*
        touching the active slot, so the previously active service is retained
        (Req 3.5).
        """
        # Guard first; raises before any mutation on unknown id.
        require_known_batch_service(service_id)
        service = self._factory(service_id, **kwargs)
        self._active_id = service_id
        self._active_service = service
        return service


# ---------------------------------------------------------------------------
# Live engine registry
# ---------------------------------------------------------------------------

#: Factory signature for a live engine: ``factory(**kwargs) -> LiveTranscriptionEngine``.
LiveEngineFactory = Callable[..., Any]


def _whisper_live_factory(**kwargs: Any) -> Any:
    """Construct the faster-whisper live engine, importing it lazily.

    The import is deferred to call time so :class:`LiveEngineRegistry` can be
    created and queried before :class:`webapp.backend.live_engine.WhisperLiveEngine`
    exists (it is implemented in Task 6.1). Once that class lands, this factory
    constructs it with no change here.
    """
    from webapp.backend.live_engine import WhisperLiveEngine  # noqa: WPS433 (lazy)

    return WhisperLiveEngine(**kwargs)


class LiveEngineRegistry:
    """Maps a live-engine id to a factory callable (Req 3.2, 3.3).

    ``whisper`` is registered by default with a lazy factory. ``aws-streaming`` is
    registered as a *documented placeholder* (a known future seam that is not yet
    implemented). Additional engines can be registered later under new ids and
    become selectable with no frontend changes (Req 3.3).

    Looking up an *unknown* id raises :class:`UnknownServiceError`; constructing a
    *placeholder* id raises :class:`UnimplementedEngineError`. Both are pure --
    they never mutate registry state (Req 3.5).
    """

    def __init__(self, register_defaults: bool = True) -> None:
        self._factories: Dict[str, LiveEngineFactory] = {}
        self._placeholder_docs: Dict[str, str] = {}
        if register_defaults:
            self.register("whisper", _whisper_live_factory)
            for engine_id, doc in LIVE_PLACEHOLDER_DOCS.items():
                self.register_placeholder(engine_id, doc)

    def register(self, engine_id: str, factory: LiveEngineFactory) -> None:
        """Register (or replace) a live-engine ``factory`` under ``engine_id``.

        Registering a real factory clears any placeholder previously recorded for
        the same id (so a placeholder seam can be "filled in" later).
        """
        if not callable(factory):
            raise TypeError(f"factory for {engine_id!r} must be callable")
        self._factories[engine_id] = factory
        self._placeholder_docs.pop(engine_id, None)

    def register_placeholder(self, engine_id: str, doc: str) -> None:
        """Document ``engine_id`` as a known-but-unimplemented future seam.

        The id appears in :meth:`placeholders` and constructing it raises
        :class:`UnimplementedEngineError` with ``doc`` as the explanation.
        """
        self._placeholder_docs[engine_id] = doc

    @property
    def available(self) -> List[str]:
        """Sorted list of *implemented* (constructible) engine ids."""
        return sorted(self._factories)

    @property
    def placeholders(self) -> Dict[str, str]:
        """Mapping of documented placeholder id -> human-readable description."""
        return dict(self._placeholder_docs)

    def is_registered(self, engine_id: str) -> bool:
        """Whether ``engine_id`` has a real (constructible) factory."""
        return engine_id in self._factories

    def is_placeholder(self, engine_id: str) -> bool:
        """Whether ``engine_id`` is a documented but unimplemented seam."""
        return engine_id in self._placeholder_docs

    def get_factory(self, engine_id: str) -> LiveEngineFactory:
        """Return the factory for ``engine_id`` or raise.

        Raises :class:`UnimplementedEngineError` for a documented placeholder and
        :class:`UnknownServiceError` for a wholly unknown id. Pure -- no state is
        changed (Req 3.5).
        """
        if engine_id in self._factories:
            return self._factories[engine_id]
        if engine_id in self._placeholder_docs:
            raise UnimplementedEngineError(engine_id, self._placeholder_docs[engine_id])
        raise UnknownServiceError(engine_id, self._all_known_ids())

    def create(self, engine_id: str, **kwargs: Any) -> Any:
        """Construct the live engine for ``engine_id``.

        ``**kwargs`` are forwarded to the engine factory. Unknown/placeholder ids
        raise as described in :meth:`get_factory` without mutating state.
        """
        factory = self.get_factory(engine_id)
        return factory(**kwargs)

    def _all_known_ids(self) -> List[str]:
        return sorted(set(self._factories) | set(self._placeholder_docs))


#: A process-wide default live-engine registry. Tasks that need the live seam can
#: import this rather than constructing their own (a fresh instance is still fine
#: for tests that want isolation).
default_live_registry = LiveEngineRegistry()


__all__ = [
    "KNOWN_BATCH_SERVICE_IDS",
    "LIVE_PLACEHOLDER_DOCS",
    "UnknownServiceError",
    "UnimplementedEngineError",
    "BatchTranscriber",
    "BatchTranscriptionService",
    "BatchServiceRegistry",
    "require_known_batch_service",
    "get_batch_service",
    "LiveEngineRegistry",
    "default_live_registry",
]
