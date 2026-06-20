"""Web application package for the Meeting Notes Generator.

Contains the FastAPI backend (`webapp.backend`) and, in later tasks, the
React + Tailwind frontend under ``webapp/frontend``. The backend wraps the
existing modules (AudioRecorder, TranscriptionService, NotesGenerator,
VersionManager, AWSHandler) behind HTTP + WebSocket APIs and adds live
transcription support.
"""
