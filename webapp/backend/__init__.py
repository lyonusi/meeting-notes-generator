"""FastAPI backend package for the live-transcription web UI.

This package orchestrates the existing application modules; it does not
reimplement recording, transcription, notes-generation, or versioning logic
(Requirement 4.5). Module placeholders are filled in by subsequent tasks:

- ``models``                 - core dataclasses and transcript-shape helpers
- ``storage``                - StorageManager (cross-process lock, WAV guard)
- ``config_service``         - ConfigService over config.py + user_settings.json
- ``transcription_registry`` - batch service adapter + LiveEngineRegistry
- ``live_engine``            - LiveTranscriptionEngine protocol + WhisperLiveEngine
- ``session_manager``        - RecordingSessionManager state machine
- ``final_pass``             - FinalTranscriptionPass orchestrator
- ``history_service``        - HistoryService (meeting history)
- ``document_service``       - DocumentService (notes/transcript CRUD + versions)
- ``ws_hub``                 - WebSocketHub broadcast + replay
- ``app``                    - FastAPI application entry point
"""
