"""FastAPI application for the live-transcription web UI backend (Task 12).

This module wires the shared :class:`~webapp.backend.context.AppContext` behind
the full HTTP + WebSocket API surface from the design's "Backend API Surface"
table:

HTTP (all under ``/api``)
-------------------------

* Devices/recording (Task 12.1): ``GET /api/devices``,
  ``POST /api/devices/select``, ``POST /api/recording/{start,pause,resume,stop}``,
  ``GET /api/recording/state``.
* Meetings/notes/transcript/config/models (Task 12.2): ``GET /api/meetings``,
  ``GET /api/meetings/{id}``, notes read/save/generate, transcript read/save,
  ``GET/PUT /api/config``, ``GET /api/models``.

WebSocket (Task 12.3)
---------------------

* ``/ws/captions`` registers the client with the :class:`WebSocketHub`, which
  replays the ascending-``start`` caption snapshot, then streams live events
  (captions, status, progress, errors). Status updates flow automatically
  because the session manager's broadcaster *is* the hub (Req 4.4).

Error envelope (Req 4.6/4.7/4.8/6.7)
------------------------------------

All errors are returned as ``{"error": {"code", "message", "resource"?}}`` with
the right status code, via FastAPI exception handlers that map the components'
domain exceptions:

* ``SessionError(reason="invalid_transition")`` -> 409 (Req 4.7)
* ``SessionError(reason="device_error")`` -> 422 (Req 4.8)
* ``NotFoundError`` -> 404, including the missing ``resource`` (Req 4.6)
* ``ConfigValidationError`` -> 422 (Req 6.7)
* ``GenerationError`` -> 502 (regeneration produced nothing; Req 7.9)
* ``UnknownServiceError`` -> 422 (Req 3.5)

The underlying components guarantee state/data is left unchanged when they
raise, so the handlers only need to translate the exception into the envelope.

Run with: ``uvicorn webapp.backend.app:app`` (module-level ``app``).
"""

from __future__ import annotations

import dataclasses
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from webapp.backend.config_service import ConfigValidationError
from webapp.backend.context import AppContext
from webapp.backend.document_service import GenerationError, NotFoundError
from webapp.backend.session_manager import SessionError
from webapp.backend.transcription_registry import (
    UnimplementedEngineError,
    UnknownServiceError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error envelope helpers
# ---------------------------------------------------------------------------


def _error_response(
    status_code: int,
    code: str,
    message: str,
    resource: Optional[str] = None,
) -> JSONResponse:
    """Build a ``{"error": {code, message, resource?}}`` JSON response (Req 4.6)."""
    error: Dict[str, Any] = {"code": code, "message": message}
    if resource is not None:
        error["resource"] = resource
    return JSONResponse(status_code=status_code, content={"error": error})


def _as_dict(obj: Any) -> Any:
    """Convert dataclasses (recursively) to JSON-serializable dicts.

    Plain dicts/lists/scalars pass through unchanged so route handlers can return
    either dataclasses (``asdict``) or already-built dicts.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [_as_dict(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(*, base_dir: Optional[str] = None, context: Optional[AppContext] = None) -> FastAPI:
    """Build and return the FastAPI application.

    Args:
        base_dir: Optional storage root forwarded to :class:`AppContext` (tests
            pass a temp dir). Ignored when ``context`` is provided.
        context: Optional pre-built :class:`AppContext` (tests inject a context
            with fakes). When omitted a real one is constructed (no AWS/PyAudio).
    """
    ctx = context if context is not None else AppContext(base_dir=base_dir)

    app = FastAPI(title="Meeting Notes Generator — Live Transcription API")
    app.state.context = ctx

    # CORS open for local dev so the Vite dev server (localhost:5173) can call the
    # API and WS during development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_exception_handlers(app)
    _register_http_routes(app, ctx)
    _register_ws_routes(app, ctx)
    _maybe_mount_frontend(app)

    return app


# ---------------------------------------------------------------------------
# Exception handlers (domain error -> envelope)
# ---------------------------------------------------------------------------


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SessionError)
    async def _handle_session_error(_request: Request, exc: SessionError) -> JSONResponse:
        # invalid_transition -> 409 (Req 4.7); device_error -> 422 (Req 4.8).
        if exc.reason == "invalid_transition":
            return _error_response(409, "invalid_transition", exc.message)
        if exc.reason == "device_error":
            return _error_response(422, "device_error", exc.message)
        return _error_response(400, exc.reason or "session_error", exc.message)

    @app.exception_handler(NotFoundError)
    async def _handle_not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        # 404 with the missing resource id; stored data left unchanged (Req 4.6).
        return _error_response(404, "not_found", str(exc), resource=exc.resource)

    @app.exception_handler(ConfigValidationError)
    async def _handle_config_invalid(
        _request: Request, exc: ConfigValidationError
    ) -> JSONResponse:
        # Invalid config value rejected; applied config unchanged (Req 6.7).
        return _error_response(422, "invalid_config", str(exc))

    @app.exception_handler(GenerationError)
    async def _handle_generation_error(
        _request: Request, exc: GenerationError
    ) -> JSONResponse:
        # Regeneration produced nothing; caller keeps prior notes (Req 7.9).
        return _error_response(502, "generation_failed", str(exc))

    @app.exception_handler(UnknownServiceError)
    async def _handle_unknown_service(
        _request: Request, exc: UnknownServiceError
    ) -> JSONResponse:
        # Unknown transcription service id; active service unchanged (Req 3.5).
        return _error_response(422, "unknown_service", str(exc))

    @app.exception_handler(UnimplementedEngineError)
    async def _handle_unimplemented_engine(
        _request: Request, exc: UnimplementedEngineError
    ) -> JSONResponse:
        return _error_response(422, "unimplemented_engine", str(exc))


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------


def _register_http_routes(app: FastAPI, ctx: AppContext) -> None:
    # -- Devices ---------------------------------------------------------

    @app.get("/api/devices")
    async def list_devices() -> List[Dict[str, Any]]:
        """List available input devices (may be empty) (Req 4.2, 5.1)."""
        return ctx.session_manager.list_devices()

    @app.post("/api/devices/select")
    async def select_device(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Persist the selected input device (Req 5.2)."""
        device_id = payload.get("device_id")
        ctx.session_manager.select_device(device_id)
        cfg = ctx.config_service.get()
        return {"input_device_id": cfg.input_device_id}

    # -- Recording control ----------------------------------------------

    @app.post("/api/recording/start")
    async def start_recording(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
        """Start a recording, validating the device (Req 4.1, 5.5, 4.8)."""
        device_id = (payload or {}).get("device_id")
        state = ctx.session_manager.start(device_id)
        return _as_dict(state)

    @app.post("/api/recording/pause")
    async def pause_recording() -> Dict[str, Any]:
        """Pause the active recording (409 if invalid transition; Req 4.7)."""
        return _as_dict(ctx.session_manager.pause())

    @app.post("/api/recording/resume")
    async def resume_recording() -> Dict[str, Any]:
        """Resume a paused recording (409 if invalid transition; Req 4.7, 5.7)."""
        return _as_dict(ctx.session_manager.resume())

    @app.post("/api/recording/stop")
    async def stop_recording() -> Dict[str, Any]:
        """Stop recording and trigger the final pass (Req 4.1, 2.1, 2.2)."""
        return _as_dict(ctx.session_manager.stop())

    @app.get("/api/recording/state")
    async def recording_state() -> Dict[str, Any]:
        """Return the current session state (drives control enablement; Req 5.3/5.4)."""
        return _as_dict(ctx.session_manager.current())

    # -- Meetings + history ---------------------------------------------

    @app.get("/api/meetings")
    async def list_meetings() -> List[Dict[str, Any]]:
        """Meeting history, descending by start (Req 4.3, 7.1)."""
        return _as_dict(ctx.history_service.list_meetings())

    @app.get("/api/meetings/{meeting_id}")
    async def get_meeting(meeting_id: str) -> Dict[str, Any]:
        """Meeting detail + versions (Req 7.2). 404 for unknown meeting (Req 4.6)."""
        summaries = ctx.history_service.list_meetings()
        summary = next((s for s in summaries if s.meeting_id == meeting_id), None)
        if summary is None:
            raise NotFoundError(
                f"meeting:{meeting_id}", f"No meeting found with id {meeting_id}"
            )
        versions = ctx.history_service.get_versions(meeting_id)
        detail = _as_dict(summary)
        detail["versions"] = _as_dict(versions)
        return detail

    # -- Notes -----------------------------------------------------------

    @app.get("/api/meetings/{meeting_id}/notes")
    async def get_notes(
        meeting_id: str, version: Optional[int] = Query(default=None)
    ) -> Dict[str, Any]:
        """Read notes content, optionally for a version (Req 7.2, 7.7)."""
        content = ctx.document_service.read_notes(meeting_id, version)
        return {"meeting_id": meeting_id, "version": version, "content": content}

    @app.put("/api/meetings/{meeting_id}/notes")
    async def save_notes(
        meeting_id: str, payload: Dict[str, Any] = Body(...)
    ) -> Dict[str, Any]:
        """Save edited notes as a new version (Req 7.4, 7.6)."""
        content = (payload or {}).get("content", "")
        result = ctx.document_service.save_notes(meeting_id, content)
        version_info = next(
            (
                v
                for v in ctx.history_service.get_versions(meeting_id)
                if v.version_num == result.version_num
            ),
            None,
        )
        return {
            "meeting_id": result.meeting_id,
            "version": result.version_num,
            "version_info": _as_dict(version_info) if version_info else None,
        }

    @app.post("/api/meetings/{meeting_id}/notes/generate")
    async def generate_notes(
        meeting_id: str, payload: Dict[str, Any] = Body(default={})
    ) -> Dict[str, Any]:
        """Regenerate notes WITHOUT persisting (Req 7.8). 404 if no transcript."""
        # Default to the configured AI model when the request omits one, so the
        # active (non-deprecated) model from ConfigService is used rather than
        # NotesGenerator's hard-coded config.py default.
        model_id = (payload or {}).get("ai_model_id") or ctx.config_service.get().ai_model_id
        content = ctx.document_service.regenerate_notes(meeting_id, model_id=model_id)
        return {"meeting_id": meeting_id, "version": None, "content": content}

    # -- Transcript ------------------------------------------------------

    @app.get("/api/meetings/{meeting_id}/transcript")
    async def get_transcript(
        meeting_id: str, version: Optional[int] = Query(default=None)
    ) -> Dict[str, Any]:
        """Read a meeting's transcript JSON (shared schema) (Req 7.2)."""
        return ctx.document_service.read_transcript_json(meeting_id)

    @app.put("/api/meetings/{meeting_id}/transcript")
    async def save_transcript(
        meeting_id: str, payload: Dict[str, Any] = Body(...)
    ) -> Dict[str, Any]:
        """Save an edited transcript (Req 7.4).

        Accepts either ``{"transcript": <shared-shape>}`` (the frontend client
        contract) or a bare ``{"text": "..."}`` body; the transcript text is
        extracted and persisted via :class:`DocumentService`.
        """
        text = _extract_transcript_text_from_payload(payload)
        result = ctx.document_service.save_transcript(meeting_id, text)
        return {"meeting_id": result.meeting_id}

    # -- Config + models -------------------------------------------------

    @app.get("/api/config")
    async def get_config() -> Dict[str, Any]:
        """Read the applied configuration (Req 6.2)."""
        return _as_dict(ctx.config_service.get())

    @app.put("/api/config")
    async def update_config(patch: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Update the configuration; validated server-side (Req 6.6, 6.7)."""
        return _as_dict(ctx.config_service.update(patch or {}))

    @app.get("/api/models")
    async def list_models() -> List[Dict[str, Any]]:
        """Available AI models for notes generation (Req 6.5)."""
        return ctx.config_service.available_models()


def _extract_transcript_text_from_payload(payload: Dict[str, Any]) -> str:
    """Extract plain transcript text from a save-transcript request body.

    Supports the typed frontend contract ``{"transcript": {results: ...}}`` and a
    simpler ``{"text": "..."}`` form. Falls back to an empty string.
    """
    payload = payload or {}
    if isinstance(payload.get("text"), str):
        return payload["text"]
    transcript = payload.get("transcript")
    if isinstance(transcript, dict):
        try:
            return transcript["results"]["transcripts"][0]["transcript"]
        except (KeyError, IndexError, TypeError):
            return ""
    if isinstance(transcript, str):
        return transcript
    return ""


# ---------------------------------------------------------------------------
# WebSocket route (Task 12.3)
# ---------------------------------------------------------------------------


def _register_ws_routes(app: FastAPI, ctx: AppContext) -> None:
    @app.websocket("/ws/captions")
    async def captions_ws(websocket: WebSocket) -> None:
        """Stream live captions/status to a client (Req 4.4, 1.3, 1.6).

        Delegates the whole lifecycle to :meth:`WebSocketHub.connect`, which
        accepts the socket, replays the ascending-``start`` caption snapshot
        (wired to ``session_manager.captions_snapshot``), then streams live
        events until the socket closes. Status updates on state changes flow
        because the session manager broadcasts through this same hub.
        """
        try:
            await ctx.hub.connect(websocket)
        except WebSocketDisconnect:
            # Normal client disconnect; the hub already unregistered the client.
            pass
        finally:
            await ctx.hub.disconnect(websocket)


# ---------------------------------------------------------------------------
# Optional static frontend mount
# ---------------------------------------------------------------------------


def _maybe_mount_frontend(app: FastAPI) -> None:
    """Serve the built Vite frontend at ``/`` if a ``dist`` directory exists.

    Optional (not required for the API): when ``webapp/frontend/dist`` is present
    it is mounted so the SPA is served from the same origin in production. The
    ``/api`` and ``/ws`` routes are registered before this catch-all mount.
    """
    dist_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "frontend",
        "dist",
    )
    if os.path.isdir(dist_dir):
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")


# Module-level ASGI app so ``uvicorn webapp.backend.app:app`` works.
app = create_app()


__all__ = ["app", "create_app"]
