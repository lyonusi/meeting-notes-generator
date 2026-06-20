"""Shared application context wiring for the FastAPI backend (Task 12).

This module builds the single, process-wide object graph the HTTP + WebSocket
API depends on. It is the central wiring point described in the design's
"Backend: Services" layer:

- one :class:`~webapp.backend.config_service.ConfigService`
- one :class:`~webapp.backend.storage.StorageManager`
- one shared ``VersionManager`` (reused by history + document services)
- one :class:`~webapp.backend.live_engine.WhisperLiveEngine` (from the registry,
  ``whisper`` by default, sized from the applied config)
- one :class:`~webapp.backend.ws_hub.WebSocketHub`
- one :class:`~webapp.backend.session_manager.RecordingSessionManager` whose
  ``broadcaster`` is the hub, wired to the live engine, storage, config service,
  and a finalizer
- one :class:`~webapp.backend.history_service.HistoryService`
- one :class:`~webapp.backend.document_service.DocumentService`

Import safety (critical)
------------------------

Constructing the context performs **no AWS calls and no PyAudio access**:

- ``ConfigService`` reads ``config.py`` + ``user_settings.json`` only.
- ``StorageManager`` / ``VersionManager`` touch the filesystem only.
- The ``WhisperLiveEngine`` is created but does **not** load its model (faster-
  whisper loads lazily on the first transcription).
- ``NotesGenerator`` (which eagerly initializes ``AWSHandler``) is built **only**
  lazily, when notes regeneration is actually requested, via a factory passed to
  ``DocumentService``.
- The ``AudioRecorder`` is built lazily by the session manager on the first
  device/record call, never at import.

The finalizer
-------------

On stop, the session manager invokes a finalizer built around
:func:`~webapp.backend.final_pass.build_finalizer`. It:

1. runs the :class:`FinalTranscriptionPass` over the recording, broadcasting
   ``final_progress`` and ``final_result`` events through the hub (Req 2.6, 2.3);
2. selects the authoritative transcript, falling back to the persisted live
   captions (read from :class:`StorageManager`) when the pass fails (Req 2.5);
3. via its ``on_result`` hook, persists the selected authoritative transcript
   through :meth:`DocumentService.save_transcript` so notes can later be
   generated from it (Req 2.4). The pass itself performs no writes, so the
   model-load "no partial writes" guarantee is preserved (Req 8.6).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, List, Optional

from webapp.backend.config_service import ConfigService
from webapp.backend.document_service import DocumentService
from webapp.backend.final_pass import (
    FinalizationResult,
    FinalTranscriptionPass,
    build_finalizer,
)
from webapp.backend.history_service import HistoryService
from webapp.backend.models import Caption, StopResult, extract_transcript_text
from webapp.backend.session_manager import RecordingSessionManager
from webapp.backend.storage import StorageManager
from webapp.backend.transcription_registry import default_live_registry
from webapp.backend.ws_hub import WebSocketHub

logger = logging.getLogger(__name__)


def _whisper_service_kwargs(config_service: ConfigService) -> dict:
    """Build batch-service kwargs for the final pass from the applied config.

    Only ``whisper`` accepts a ``model_size``; ``aws``/``mac`` take none, so we
    only forward ``model_size`` when the active service is ``whisper`` to avoid a
    ``TypeError`` from the underlying factory.
    """
    cfg = config_service.get()
    if cfg.transcription_service == "whisper":
        return {"model_size": cfg.whisper_model_size}
    return {}


class _AuthoritativeTranscriptPersister:
    """Builds a ``build_finalizer`` finalizer that persists the chosen transcript.

    ``build_finalizer``'s ``on_result`` hook only receives the
    :class:`FinalizationResult` (which does not carry the meeting id), so this
    small object captures the ``StopResult.meeting_id`` for the in-flight stop
    before delegating to the inner finalizer. Finalization is synchronous and
    single-session (the session manager calls the finalizer inline on ``stop``),
    so a single captured id is always correct.
    """

    def __init__(
        self,
        *,
        final_pass: FinalTranscriptionPass,
        service_id: str,
        document_service: DocumentService,
        storage: StorageManager,
        hub: WebSocketHub,
        service_kwargs: dict,
    ) -> None:
        self._document_service = document_service
        self._current_meeting_id: Optional[str] = None
        self._inner = build_finalizer(
            final_pass,
            service_id,
            captions_provider=self._captions_for,
            broadcaster=hub,
            on_result=self._persist_result,
            **service_kwargs,
        )
        self._storage = storage

    def __call__(self, stop_result: StopResult) -> None:
        """Run the finalizer for ``stop_result`` (invoked by the session manager)."""
        self._current_meeting_id = getattr(stop_result, "meeting_id", None)
        self._inner(stop_result)

    def _captions_for(self, meeting_id: Optional[str]) -> List[Caption]:
        """Fallback captions provider: read persisted captions from storage (Req 2.5)."""
        if not meeting_id:
            return []
        try:
            return self._storage.read_captions(meeting_id)
        except FileNotFoundError:
            return []
        except Exception:  # pragma: no cover - best-effort fallback source
            logger.exception("Failed to read persisted captions for %r", meeting_id)
            return []

    def _persist_result(self, result: FinalizationResult) -> None:
        """Persist the selected authoritative/fallback transcript (Req 2.4)."""
        meeting_id = self._current_meeting_id
        if result.transcript is None or not meeting_id:
            return
        try:
            text = extract_transcript_text(result.transcript)
        except Exception:  # pragma: no cover - transcript already validated upstream
            logger.exception("Final transcript had unexpected shape for %r", meeting_id)
            return
        try:
            self._document_service.save_transcript(meeting_id, text)
        except Exception:  # pragma: no cover - persistence is best-effort here
            logger.exception("Failed to persist final transcript for %r", meeting_id)


class AppContext:
    """The shared object graph for the backend, built without AWS/PyAudio access."""

    def __init__(
        self,
        *,
        base_dir: Optional[str] = None,
        auto_finalize: bool = True,
    ) -> None:
        """Construct the full backend context.

        Args:
            base_dir: Optional root for ``notes``/``recordings`` storage. Defaults
                to the project root (shared with the tkinter app). Tests pass a
                temp directory for isolation.
            auto_finalize: Forwarded to the session manager; when True (default)
                ``stop`` completes finalization synchronously.
        """
        # 1) Config + storage foundations (filesystem/config only; no AWS).
        self.config_service = ConfigService()
        self.storage = StorageManager(base_dir=base_dir)

        # One shared VersionManager so history + document services agree on layout.
        from version_manager import VersionManager  # top-level module (fs only)

        self.version_manager = VersionManager(self.storage.notes_dir())

        # 2) WebSocket fan-out hub (the session manager's broadcaster).
        self.hub = WebSocketHub()

        # 3) Live engine from the registry (whisper); model loads lazily on first
        #    transcription, so this does not touch faster-whisper here.
        cfg = self.config_service.get()
        self.live_engine = default_live_registry.create(
            "whisper",
            model_size=cfg.whisper_model_size,
            live_window_seconds=cfg.live_window_seconds,
            live_overlap_seconds=cfg.live_overlap_seconds,
        )

        # 4) History + document services. NotesGenerator is only built lazily for
        #    regeneration (it initializes AWSHandler), so pass a factory, never an
        #    instance, and do NOT give HistoryService a factory (it reads file
        #    headings for titles without AWS).
        self.history_service = HistoryService(version_manager=self.version_manager)
        self.document_service = DocumentService(
            storage=self.storage,
            version_manager=self.version_manager,
            notes_generator_factory=self._build_notes_generator,
        )

        # 5) Finalizer: run the final pass, broadcast progress/result, and persist
        #    the authoritative transcript via DocumentService (Req 2.4/2.6).
        final_pass = FinalTranscriptionPass(
            final_pass_max_attempts=cfg.final_pass_max_attempts
        )
        finalizer = _AuthoritativeTranscriptPersister(
            final_pass=final_pass,
            service_id=cfg.transcription_service,
            document_service=self.document_service,
            storage=self.storage,
            hub=self.hub,
            service_kwargs=_whisper_service_kwargs(self.config_service),
        )

        # 6) The session manager: hub as broadcaster, live engine, storage, config,
        #    finalizer. The AudioRecorder is built lazily on first device/record use.
        self.session_manager = RecordingSessionManager(
            config_service=self.config_service,
            live_engine=self.live_engine,
            broadcaster=self.hub,
            storage=self.storage,
            finalizer=finalizer,
            auto_finalize=auto_finalize,
        )

        # Wire the hub's on-connect replay to the session's caption snapshot (Req 1.6).
        self.hub.set_snapshot_provider(self.session_manager.captions_snapshot)

        # Lazily-built NotesGenerator cache (regenerate path only).
        self._notes_generator: Any = None
        self._notes_generator_lock = threading.Lock()

    def _build_notes_generator(self) -> Any:
        """Lazily construct and cache a ``NotesGenerator`` (initializes AWS).

        Invoked only by :class:`DocumentService` when notes regeneration is
        requested, so importing/constructing the context never triggers AWS.
        """
        with self._notes_generator_lock:
            if self._notes_generator is None:
                from notes_generator import NotesGenerator  # top-level (inits AWS)

                self._notes_generator = NotesGenerator()
            return self._notes_generator


__all__ = ["AppContext"]
