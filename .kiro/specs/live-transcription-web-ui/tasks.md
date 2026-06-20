# Implementation Plan: Live Transcription Web UI

## Overview

This plan implements the live-transcription + web-UI feature by wrapping the existing Python
modules (`AudioRecorder`, `TranscriptionService`, `NotesGenerator`, `VersionManager`,
`AWSHandler`) behind a FastAPI backend and building a React + Tailwind frontend.

The build order is incremental and test-driven:

1. Set up backend/frontend project structure and a shared **fake transcriber** test helper.
2. Build the storage/config foundation (`StorageManager` lock + WAV guard, `ConfigService`).
3. Build the pluggable transcription seam (registry, `WhisperLiveEngine`).
4. Build session orchestration (`RecordingSessionManager`, `FinalTranscriptionPass`,
   `WebSocketHub`) and document/history services.
5. Expose the HTTP + WebSocket API surface.
6. Scaffold the frontend, build the caption-store reducer, WebSocket client, and each view.
7. Wire everything together and add integration / smoke / coexistence tests.

Property-based tests use `hypothesis` (Python) and `fast-check` (frontend caption reducer),
run a minimum of **100 iterations**, exercise a **fake transcriber** for cost/isolation, and
are tagged `Feature: live-transcription-web-ui, Property {n}`.

Existing modules are reused, never reimplemented (Req 4.5).

## Tasks

- [x] 1. Set up backend project structure and shared test fixtures
  - Create a `webapp/backend/` package with module placeholders for `models`, `storage`,
    `config_service`, `transcription_registry`, `live_engine`, `session_manager`,
    `final_pass`, `history_service`, `document_service`, `ws_hub`, and `app` (FastAPI entry).
  - Add backend dependencies to `requirements.txt`: `fastapi`, `uvicorn[standard]`,
    `websockets`, `hypothesis`, `pytest`, `pytest-asyncio`, `httpx` (test client).
  - Create `webapp/backend/tests/` with a `pytest` config and a `FakeTranscriber` test
    helper that returns deterministic segments and can be configured to fail K times before
    succeeding (used by live-engine, final-pass, and selection property tests).
  - _Requirements: 4.5, 3.1_

- [x] 2. Define core backend data models
  - [x] 2.1 Implement `Caption`, `SessionState`, `StopResult`, `TranscriptResult` shape
    helpers, `AppConfig`, `MeetingSummary`, and `NotesVersion` dataclasses in `models`.
    - `Caption` is frozen with `start`, `end`, `text`, `status` (`interim|final`); identity
      for de-dup is `start`.
    - Add a `transcript_result` builder/validator that asserts the shared schema
      `results.transcripts[0].transcript` is a string.
    - _Requirements: 1.2, 3.1, 2.4, 6.1, 6.3, 7.1, 7.7_

  - [ ]* 2.2 Write property test for transcript-structure conformance
    - **Property 9: Transcript structure conformance across services**
    - **Validates: Requirements 3.1**
    - Tag: `Feature: live-transcription-web-ui, Property 9`

- [x] 3. Implement StorageManager with cross-process lock and WAV-location guard
  - [x] 3.1 Implement `StorageManager` in `storage`
    - `recordings_dir()` (outside notes dir) and `notes_dir()` accessors.
    - `write_lock()` context manager using a `fcntl.flock` lockfile under
      `notes/metadata/.write.lock`.
    - Atomic writes (`temp file` + `os.replace`) for `write_notes`, `write_transcript`,
      `write_captions`; `read_text`.
    - A guard that rejects any write whose target is a `.wav` path under `notes_dir`.
    - _Requirements: 8.1, 8.2, 8.3, 9.3, 2.9_

  - [ ]* 3.2 Write property test for storage-location invariant
    - **Property 23: Storage-location invariant**
    - **Validates: Requirements 8.1, 8.2, 8.3**
    - Tag: `Feature: live-transcription-web-ui, Property 23`

  - [ ]* 3.3 Write property test for caption persistence round-trip
    - **Property 8: Caption persistence round-trip**
    - **Validates: Requirements 2.9**
    - Tag: `Feature: live-transcription-web-ui, Property 8`

  - [ ]* 3.4 Write property test for concurrent-write atomicity
    - **Property 25: Concurrent writes are atomic**
    - **Validates: Requirements 7.5, 9.3**
    - Tag: `Feature: live-transcription-web-ui, Property 25`

- [x] 4. Implement ConfigService
  - [x] 4.1 Implement `ConfigService` over `config.py` defaults + `user_settings.json`
    - `get()`, `update(patch)` with validation of `transcription_service`,
      `whisper_model_size`, and `ai_model_id` against allowed option sets; reject
      out-of-range and retain last-applied config.
    - Persist applied config to `user_settings.json` (survives restart) and expose
      `available_models()` via `AWSHandler.list_available_models`.
    - Add `select_device(id)` persistence and a `snapshot()` for in-flight operations.
    - _Requirements: 6.6, 6.7, 6.9, 6.5, 5.2, 6.8_

  - [ ]* 4.2 Write property test for config validation and round-trip persistence
    - **Property 18: Configuration validation and round-trip persistence**
    - **Validates: Requirements 6.6, 6.7, 6.9**
    - Tag: `Feature: live-transcription-web-ui, Property 18`

  - [ ]* 4.3 Write property test for in-flight config snapshot isolation
    - **Property 19: In-flight operations use a config snapshot**
    - **Validates: Requirements 6.8**
    - Tag: `Feature: live-transcription-web-ui, Property 19`

  - [ ]* 4.4 Write property test for device-selection persistence
    - **Property 14: Device selection persistence**
    - **Validates: Requirements 5.2**
    - Tag: `Feature: live-transcription-web-ui, Property 14`

- [x] 5. Implement the pluggable transcription registry seam
  - [x] 5.1 Implement batch `TranscriptionService` registry adapter and `LiveEngineRegistry`
    - Wrap the existing `transcription.py` factory so `whisper`/`aws`/`mac` are requested by
      id through one interface returning the shared `TranscriptResult` shape.
    - Implement `LiveEngineRegistry` (id -> factory) with `whisper` registered and an
      `aws-streaming` placeholder documented.
    - Reject unknown ids with an error and leave the active service unchanged.
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.3_

  - [ ]* 5.2 Write property test for unknown-service rejection
    - **Property 10: Unknown-service rejection preserves active service**
    - **Validates: Requirements 3.5**
    - Tag: `Feature: live-transcription-web-ui, Property 10`

  - [ ]* 5.3 Write unit tests for the factory and dependency-unavailable path
    - `get_service('whisper'|'aws'|'mac')` returns conforming instances (3.2, 3.4).
    - Dependency-unavailable init returns no partial transcript (3.6).
    - A newly registered id is selectable with no frontend change (3.3 smoke).
    - _Requirements: 3.2, 3.4, 3.6, 3.3_

- [x] 6. Implement WhisperLiveEngine (rolling/overlapping windows)
  - [x] 6.1 Implement `LiveTranscriptionEngine` protocol and `WhisperLiveEngine`
    - `start/feed/poll/stop`; maintain an in-memory PCM buffer and transcribe rolling
      windows of `live_window_seconds + live_overlap_seconds`.
    - Apply the commit boundary: segments ending before the boundary emit `status=final`;
      overlapping-tail segments emit `status=interim` keyed by `start` and may be revised.
    - Load faster-whisper from `~/.cache/huggingface/hub`, downloading on cache miss.
    - _Requirements: 1.1, 1.2, 1.5, 1.7, 8.4, 8.5_

  - [ ]* 6.2 Write unit tests for commit-boundary interim/final classification
    - Use `FakeTranscriber` to assert tail segments are interim and pre-boundary segments are
      final, and that a later window can revise an interim caption at the same `start`.
    - _Requirements: 1.2, 1.7_

- [x] 7. Implement RecordingSessionManager state machine and audio handling
  - [x] 7.1 Implement `RecordingSessionManager` core state machine
    - `start/pause/resume/stop/current/list_devices/select_device` enforcing the
      idle→recording→paused→finalizing transitions; invalid transitions return an error and
      leave state unchanged.
    - Validate the selected device against the current device list + accessibility on start;
      on failure stay idle, retain prior selection, surface a device-error reason.
    - _Requirements: 4.1, 4.7, 4.8, 5.5, 5.6, 5.3, 5.4_

  - [ ]* 7.2 Write property test for recording state-machine transition validity
    - **Property 11: Recording state-machine transition validity**
    - **Validates: Requirements 4.1, 4.7**
    - Tag: `Feature: live-transcription-web-ui, Property 11`

  - [ ]* 7.3 Write property test for start device validation and selection retention
    - **Property 13: Start device validation and selection retention**
    - **Validates: Requirements 4.8, 5.5, 5.6**
    - Tag: `Feature: live-transcription-web-ui, Property 13`

  - [x] 7.4 Implement pause/resume audio append and silence classification on stop
    - Drive `AudioRecorder` so the saved WAV concatenates only non-paused intervals in order.
    - Compute `was_silent`/`peak_amplitude` and build `StopResult` with `has_recording`.
    - _Requirements: 5.7, 5.8_

  - [ ]* 7.5 Write property test for pause/resume audio preservation and append
    - **Property 16: Pause/resume preserves and appends audio**
    - **Validates: Requirements 5.7**
    - Tag: `Feature: live-transcription-web-ui, Property 16`

  - [ ]* 7.6 Write property test for silence classification threshold
    - **Property 17: Silence classification threshold**
    - **Validates: Requirements 5.8**
    - Tag: `Feature: live-transcription-web-ui, Property 17`

- [x] 8. Implement caption broadcast loop, persistence, and chunk-failure resilience
  - [x] 8.1 Implement the session poll/broadcast loop and caption snapshot/persistence
    - Background loop polls the live engine, appends to an ordered de-duplicated snapshot
      keyed by `start`, broadcasts caption events, and persists captions on stop via
      `StorageManager.write_captions`.
    - On a per-window transcription exception, emit a `chunk_error{chunk_id}`, retain prior
      captions, and continue with subsequent windows.
    - _Requirements: 1.3, 1.6, 1.8, 2.9_

  - [ ]* 8.2 Write property test for chunk-failure resilience
    - **Property 3: Chunk-failure resilience**
    - **Validates: Requirements 1.8**
    - Tag: `Feature: live-transcription-web-ui, Property 3`

  - [ ]* 8.3 Write property test for caption replay completeness on (re)connect
    - **Property 2: Caption replay completeness on (re)connect**
    - **Validates: Requirements 1.6**
    - Tag: `Feature: live-transcription-web-ui, Property 2`

- [x] 9. Implement FinalTranscriptionPass
  - [x] 9.1 Implement `FinalTranscriptionPass.run` with progress, retries, and selection
    - Use the registry batch service; report progress 0–100 via `progress_cb`
      (non-decreasing, reaching 100 on success).
    - Retry up to `final_pass_max_attempts`; on terminal failure retain the WAV + persisted
      captions and report failure; abort with no partial notes/transcript writes if the
      model fails to load.
    - Implement authoritative-vs-fallback transcript selection for notes input, and the
      start-decision (start iff non-empty recording, else report missing-recording).
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 2.7, 2.8, 8.6_

  - [ ]* 9.2 Write property test for final-pass start decision
    - **Property 4: Final-pass start decision**
    - **Validates: Requirements 2.1, 2.2**
    - Tag: `Feature: live-transcription-web-ui, Property 4`

  - [ ]* 9.3 Write property test for authoritative-preferred transcript selection
    - **Property 5: Authoritative-preferred transcript selection**
    - **Validates: Requirements 2.4, 2.5**
    - Tag: `Feature: live-transcription-web-ui, Property 5`

  - [ ]* 9.4 Write property test for final-pass progress bounds and monotonicity
    - **Property 6: Final-pass progress bounds and monotonicity**
    - **Validates: Requirements 2.6**
    - Tag: `Feature: live-transcription-web-ui, Property 6`

  - [ ]* 9.5 Write property test for retry count and retention on failure
    - **Property 7: Final-pass retry count and retention on failure**
    - **Validates: Requirements 2.7, 2.8**
    - Tag: `Feature: live-transcription-web-ui, Property 7`

  - [ ]* 9.6 Write property test for model-load failure writing nothing to notes
    - **Property 24: Model-load failure writes nothing to the notes folder**
    - **Validates: Requirements 8.6**
    - Tag: `Feature: live-transcription-web-ui, Property 24`

- [x] 10. Implement WebSocketHub
  - [x] 10.1 Implement `WebSocketHub` broadcast and on-connect replay
    - Track clients; broadcast typed events (`caption`, `status`, `final_progress`,
      `chunk_error`, `final_result`, `missing_recording`, `silent_warning`, `device_error`).
    - On connect/reconnect, send the ascending-`start` caption snapshot before live events.
    - _Requirements: 1.3, 1.6, 4.4, 2.6, 1.8, 2.3, 2.5, 2.8, 2.2, 5.8, 5.6_

- [x] 11. Implement HistoryService and DocumentService
  - [x] 11.1 Implement `HistoryService`
    - Wrap `VersionManager.get_all_meetings_with_metadata()` +
      `NotesGenerator.get_notes_list()` to return the descending-ordered meeting list and
      versions ordered by creation timestamp descending.
    - _Requirements: 7.1, 7.7_

  - [ ]* 11.2 Write property test for descending ordering of history and versions
    - **Property 20: Descending timestamp ordering of history and versions**
    - **Validates: Requirements 7.1, 7.7**
    - Tag: `Feature: live-transcription-web-ui, Property 20`

  - [x] 11.3 Implement `DocumentService`
    - Read/edit/save notes and transcripts through `StorageManager` (under lock) +
      `VersionManager`/`NotesGenerator` versioned save path.
    - Saving for a meeting with an existing version creates a strictly greater version,
      leaves prior version files unchanged, and supports read-back; regeneration does not
      persist; not-found leaves stored data unchanged.
    - _Requirements: 7.4, 7.5, 7.6, 7.8, 4.6_

  - [ ]* 11.4 Write property test for version monotonicity, retention, and read-back
    - **Property 21: Version monotonicity, retention, and read-back**
    - **Validates: Requirements 7.4, 7.6**
    - Tag: `Feature: live-transcription-web-ui, Property 21`

  - [ ]* 11.5 Write property test for regeneration not persisting
    - **Property 22: Regeneration does not persist**
    - **Validates: Requirements 7.8**
    - Tag: `Feature: live-transcription-web-ui, Property 22`

  - [ ]* 11.6 Write property test for not-found requests leaving data unchanged
    - **Property 12: Not-found requests leave stored data unchanged**
    - **Validates: Requirements 4.6**
    - Tag: `Feature: live-transcription-web-ui, Property 12`

- [x] 12. Implement the HTTP API surface (FastAPI)
  - [x] 12.1 Implement device and recording routes
    - `GET /api/devices`, `POST /api/devices/select`, `POST /api/recording/{start,pause,
      resume,stop}`, `GET /api/recording/state`.
    - Map errors to the `{error:{code,message,resource?}}` envelope: 409 invalid transition,
      422 unavailable device, leaving state unchanged.
    - _Requirements: 4.1, 4.2, 4.7, 4.8, 5.1, 5.2, 5.5, 2.1, 2.2_

  - [x] 12.2 Implement meetings, notes, transcript, config, and models routes
    - `GET /api/meetings`, `GET /api/meetings/{id}`, notes read/save/generate, transcript
      read/save, `GET/PUT /api/config`, `GET /api/models`.
    - 404 with resource id for unknown meeting/resource, leaving data unchanged.
    - _Requirements: 4.3, 4.6, 6.2, 6.5, 6.6, 6.7, 7.2, 7.4, 7.6, 7.8_

  - [x] 12.3 Implement the `/ws/captions` WebSocket endpoint
    - Register the client with `WebSocketHub`, trigger replay, then stream live events; emit
      `status` updates on state changes.
    - _Requirements: 4.4, 1.3, 1.6_

  - [ ]* 12.4 Write API integration tests for error envelopes and not-found behavior
    - Invalid transition (409), unavailable device (422), unknown meeting (404) leave
      state/data unchanged; device list empty-state and populated cases.
    - _Requirements: 4.2, 4.6, 4.7, 4.8, 5.1_

- [ ] 13. Checkpoint - backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Scaffold the React + Tailwind frontend
  - Create `webapp/frontend/` with Vite + React + TypeScript + Tailwind, a Zustand store, and
    `fast-check` + `vitest` configured for property tests.
  - Define the store shape: `recordingState`, `captions`, `config`, `devices`, `meetings`,
    open document/version.
  - _Requirements: 4.1, 5.3, 5.4_

- [x] 15. Implement the typed API client
  - [x] 15.1 Implement an `api` client module covering all HTTP endpoints
    - Typed request/response wrappers, error-envelope handling, and a backend-unavailable
      signal the UI can surface.
    - _Requirements: 4.1, 4.2, 4.3, 4.6, 6.2, 6.5, 6.6, 7.2, 7.4, 7.8, 9.5_

- [x] 16. Implement the caption-store reducer
  - [x] 16.1 Implement the pure caption-store reducer
    - Insert/replace captions keyed by `start`, keep ascending-`start` order, let `final`
      supersede `interim` at the same `start`, and apply `chunk_error` without removing any
      displayed caption.
    - _Requirements: 1.4, 1.7, 1.9_

  - [ ]* 16.2 Write fast-check property test for the caption store
    - **Property 1: Caption store ordering, uniqueness, and latest-wins**
    - **Validates: Requirements 1.4, 1.7, 1.9**
    - Tag: `Feature: live-transcription-web-ui, Property 1`

- [x] 17. Implement the useWebSocket hook
  - [x] 17.1 Implement `useWebSocket` connecting to `/ws/captions`
    - Apply replayed captions first then live events through the reducer; auto-reconnect;
      on `chunk_error` show an inline error while retaining displayed captions.
    - _Requirements: 1.3, 1.6, 1.9_

- [x] 18. Implement the Live Recording view
  - [x] 18.1 Implement `LiveRecordingView` with `RecordingControls`, `CaptionStream`,
    `DeviceSelector`
    - Controls enable/disable strictly by recording state; device selector shows names with
      an empty-state; caption stream renders captions ascending by `start`.
    - _Requirements: 1.4, 5.1, 5.3, 5.4_

  - [ ]* 18.2 Write component tests for control enablement and device empty-state
    - Assert start enabled only when idle; pause/stop only while recording/paused; empty
      device list renders empty-state.
    - _Requirements: 5.1, 5.3, 5.4_

- [x] 19. Implement the Configuration view
  - [x] 19.1 Implement `ConfigurationView`
    - Service options exactly `whisper|aws|mac`; whisper-model-size options exactly
      `tiny|base|small|medium|large` enabled iff service is `whisper`; AI model from backend
      list; pre-select last-applied config; show error on rejected value.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.7_

  - [ ]* 19.2 Write fast-check property test for control enablement function of state
    - **Property 15: Control enablement is a function of state**
    - **Validates: Requirements 5.3, 5.4, 6.4**
    - Tag: `Feature: live-transcription-web-ui, Property 15`

- [x] 20. Implement the Meeting History view
  - [x] 20.1 Implement `MeetingHistoryView`
    - Render meetings ordered by start timestamp descending; on selection load notes +
      transcript; on load error show a message and retain the list state.
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 21. Implement the Notes/Transcript view
  - [x] 21.1 Implement `NotesTranscriptView` with `NotesEditor`, `TranscriptViewer`,
    `VersionSelector`
    - View/edit/save notes with a save confirmation; save creates a new version on success
      and shows an error on failure; version selector lists versions descending; regenerate
      shows notes for review without persisting and retains prior notes on failure.
    - _Requirements: 7.2, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9_

  - [ ]* 21.2 Write component tests for save confirmation, regeneration, and load-error paths
    - Save success confirmation + new version; regeneration failure retains displayed notes;
      notes/transcript read error keeps history intact.
    - _Requirements: 7.3, 7.5, 7.9_

- [x] 22. Wire the frontend application together
  - [x] 22.1 Implement `App`, router, layout/nav, and backend-unavailable indicator
    - Connect all views to the store, api client, and `useWebSocket`; show an unavailable
      indicator when the backend is down.
    - _Requirements: 9.5, 1.3, 4.1_

- [ ] 23. Add integration, smoke, and coexistence tests
  - [ ]* 23.1 Write end-to-end live-path integration test
    - Feed a short fixed WAV through `WhisperLiveEngine`, assert captions are produced and
      streamed to a connected WS test client; final pass produces a stored authoritative
      transcript; model-cache-miss download fallback with a mocked downloader.
    - _Requirements: 1.1, 1.3, 4.4, 2.3, 8.5_

  - [ ]* 23.2 Write smoke tests for tkinter coexistence and loader cache
    - tkinter UI launches and completes startup unchanged; faster-whisper loader points at
      `~/.cache/huggingface/hub`; a newly registered engine id is selectable with no frontend
      change.
    - _Requirements: 9.1, 8.4, 3.3_

  - [ ]* 23.3 Write coexistence/concurrency tests for shared storage
    - Concurrent simulated tkinter + web writers hammer the same notes file through the write
      lock; assert final file equals one complete payload and no version file is partial;
      read-after-write consistency across both paths; backend-down leaves tkinter operable.
    - _Requirements: 9.2, 9.3, 9.4, 9.5_

- [ ] 24. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP, but
  each maps to a design property or required behavior for traceability.
- Each of Properties 1–25 is implemented by exactly one property-based test, placed close to
  the code it validates so regressions surface early.
- Property tests run a minimum of 100 iterations, use the `FakeTranscriber` for cost/
  isolation, and are tagged `Feature: live-transcription-web-ui, Property {n}`.
- Storage hygiene (WAVs never in the notes folder) and tkinter coexistence on shared storage
  with serialized writes are enforced by `StorageManager` (tasks 3, 23.3) and verified by
  Properties 23 and 25.
- Existing modules are orchestrated, not reimplemented (Req 4.5).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "14.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "4.1", "5.1", "15.1", "16.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4", "4.2", "4.3", "4.4", "5.2", "5.3", "6.1", "16.2", "17.1"] },
    { "id": 4, "tasks": ["6.2", "7.1", "11.1", "11.3", "18.1", "19.1", "20.1", "21.1"] },
    { "id": 5, "tasks": ["7.2", "7.3", "7.4", "8.1", "9.1", "10.1", "11.2", "11.4", "11.5", "11.6", "18.2", "19.2", "21.2"] },
    { "id": 6, "tasks": ["7.5", "7.6", "8.2", "8.3", "9.2", "9.3", "9.4", "9.5", "9.6", "12.1", "12.2", "12.3", "22.1"] },
    { "id": 7, "tasks": ["12.4", "23.1", "23.2", "23.3"] }
  ]
}
```
