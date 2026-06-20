# Requirements Document

## Introduction

This feature adds two related capabilities to the Meeting Notes Generator:

1. **Live transcription** — display transcribed captions while a meeting is still being
   recorded, instead of only after recording stops. The chosen approach is a hybrid:
   chunked **local faster-whisper** produces low-latency live captions during the
   meeting, and when recording stops a **full accurate transcription pass** runs over
   the complete recording to produce the authoritative transcript used for notes
   generation (the "A + C hybrid"). The transcription layer must remain pluggable so a
   streaming engine (e.g. AWS Transcribe Streaming) can be added later.

2. **Modern web UI** — a new browser-based interface that replaces the existing tkinter
   desktop UI as the primary interface. The system is split into a Python **backend** that
   exposes the existing notes-generation, transcription, and AWS logic via an API
   (FastAPI), and a separate modern web **frontend** (React/Tailwind). Live captions
   stream to the frontend in real time over WebSockets. The existing tkinter UI remains
   available during the transition and is deprecated gradually.

The new web UI must preserve all functionality currently available in the tkinter UI:
device/recording-source selection, start/pause/stop recording, transcription service
selection, whisper model size selection, AI model selection, meeting history, viewing /
editing / saving notes and transcripts, and note versioning.

This spec is independent of the separate "live-note-transcriber / live-transcription-notes"
spec that exists in the user's Obsidian vault.

## Glossary

- **Backend**: The Python service (FastAPI) that exposes recording, transcription, and
  notes-generation operations over HTTP and WebSocket APIs.
- **Frontend**: The browser-based web client (React/Tailwind) that is the new primary user
  interface.
- **Live_Transcription_Engine**: The component that produces low-latency interim captions
  from audio chunks during recording, using local faster-whisper.
- **Final_Transcription_Pass**: The full-file, higher-accuracy transcription run over the
  complete recording after recording stops, producing the authoritative transcript.
- **Transcription_Service**: A pluggable transcription provider. Current options are
  `whisper` (local faster-whisper), `aws` (AWS Transcribe batch), and `mac` (macOS speech
  recognition).
- **Audio_Recorder**: The existing component that captures audio from a single input
  device and writes a WAV file.
- **Input_Device**: The audio capture device selected for recording. Capturing system /
  meeting audio requires a loopback device such as BlackHole selected as the input.
- **Caption**: A segment of transcribed text shown to the user during recording. Each
  Caption includes its text, a start timestamp, an end timestamp, and a status of either
  interim (subject to revision) or final.
- **Authoritative_Transcript**: The transcript produced by the Final_Transcription_Pass,
  used as input to notes generation.
- **Notes_Generator**: The existing component that generates meeting notes from a transcript
  via AWS Bedrock.
- **Meeting_History**: The list of previously recorded meetings with their notes and
  transcripts.
- **Notes_Version**: A distinct saved revision of a meeting's notes, identified by a creation
  timestamp / version suffix on the notes filename.
- **WebSocket_Channel**: The real-time connection over which the Backend streams captions
  and status updates to the Frontend.
- **Obsidian_Vault**: The git-backed vault into which the notes and recordings folders are
  symlinked; large WAV files must not be committed into it.

## Requirements

### Requirement 1: Live captions during recording

**User Story:** As a meeting participant, I want to see transcribed captions while the
meeting is still being recorded, so that I get immediate feedback and can confirm that
audio is being captured correctly.

#### Acceptance Criteria

1. WHILE a recording is in progress, THE Live_Transcription_Engine SHALL produce Captions
   from the captured audio using local faster-whisper.
2. THE Live_Transcription_Engine SHALL produce each Caption with its text, a start
   timestamp, an end timestamp, and a status of either interim or final.
3. WHEN a new Caption is produced, THE Backend SHALL send the Caption to the Frontend over
   the WebSocket_Channel.
4. WHEN the Frontend receives a Caption, THE Frontend SHALL display the Caption in the live
   transcription view ordered by ascending start timestamp within 1 second of receipt.
5. WHILE a recording is in progress, THE Live_Transcription_Engine SHALL emit each Caption
   within 10 seconds of the corresponding audio being captured.
6. WHEN the WebSocket_Channel connects or reconnects while a recording is in progress, THE
   Backend SHALL send all Captions already produced for that recording before sending
   subsequently produced Captions.
7. WHERE the Live_Transcription_Engine revises a previously emitted interim Caption, THE
   Frontend SHALL replace the prior interim Caption that has the same start timestamp with
   the revised text and SHALL NOT create a duplicate entry.
8. IF the Live_Transcription_Engine fails to process an audio chunk, THEN THE Backend SHALL
   send an error notification identifying the affected chunk to the Frontend, SHALL retain
   previously produced Captions, and SHALL continue processing subsequent audio chunks.
9. WHEN the Frontend receives a chunk-processing error notification, THE Frontend SHALL
   display an error indication while retaining the Captions already displayed.

### Requirement 2: Final accurate transcription pass

**User Story:** As a user generating meeting notes, I want a full accurate transcription of
the complete recording after the meeting ends, so that the notes are based on the most
reliable transcript rather than the lower-latency live captions.

#### Acceptance Criteria

1. WHEN a recording stops and a non-empty recording file exists, THE Backend SHALL start a
   Final_Transcription_Pass over the complete recording file.
2. IF a recording stops but no non-empty recording file exists, THEN THE Backend SHALL NOT
   start a Final_Transcription_Pass and SHALL report the missing-recording condition to the
   Frontend.
3. WHEN the Final_Transcription_Pass completes successfully, THE Backend SHALL store the
   result as the Authoritative_Transcript.
4. WHEN notes are generated for a meeting that has an Authoritative_Transcript, THE
   Notes_Generator SHALL use the Authoritative_Transcript as input.
5. IF no Authoritative_Transcript exists because the Final_Transcription_Pass failed, THEN
   THE Notes_Generator SHALL use the persisted live Captions as input.
6. WHILE the Final_Transcription_Pass is running, THE Backend SHALL report progress to the
   Frontend over the WebSocket_Channel as a completion percentage from 0 to 100.
7. IF the Final_Transcription_Pass fails, THEN THE Backend SHALL retry it up to a configured
   maximum number of attempts before declaring failure.
8. IF the Final_Transcription_Pass fails after the maximum attempts and no fallback
   transcript is available, THEN THE Backend SHALL report the failure to the Frontend and
   SHALL retain the live Captions and the recording file.
9. THE Backend SHALL persist the live Captions produced during recording so that they remain
   available if the Final_Transcription_Pass fails.

### Requirement 3: Pluggable transcription architecture

**User Story:** As a developer, I want the transcription layer to be pluggable, so that I can
add a streaming engine such as AWS Transcribe Streaming in the future without rewriting the
recording or UI layers.

#### Acceptance Criteria

1. THE Backend SHALL expose transcription through an interface that accepts an audio source
   and an optional progress callback and returns the shared transcript output structure,
   independent of the specific transcription implementation.
2. WHEN a Transcription_Service is requested by its identifier, THE Backend SHALL return an
   instance that conforms to the transcription interface.
3. WHERE a new Transcription_Service implementing the transcription interface is registered
   with a unique identifier, THE Backend SHALL support selecting that service with zero
   changes to the Frontend source files.
4. THE Backend SHALL provide the existing `whisper`, `aws`, and `mac` Transcription_Service
   options for the Final_Transcription_Pass through the same interface.
5. IF a Transcription_Service is requested by an identifier that is not registered, THEN THE
   Backend SHALL reject the request with an error and SHALL retain the currently active
   Transcription_Service.
6. IF a selected Transcription_Service cannot be initialized because its runtime
   dependencies are unavailable, THEN THE Backend SHALL report the failure and SHALL NOT
   return a partial transcript.

### Requirement 4: Web backend API

**User Story:** As a frontend developer, I want the existing recording, transcription, and
notes logic exposed through an API, so that the web frontend can drive all application
functionality without depending on the tkinter UI.

#### Acceptance Criteria

1. WHEN the Frontend sends a request to start, pause, or stop recording, THE Backend SHALL
   apply the requested recording-state transition and return a confirmation response within
   2 seconds.
2. WHEN the Frontend requests the list of available Input_Devices, THE Backend SHALL return
   the list of currently available Input_Devices within 2 seconds, returning an empty list
   when no Input_Devices are available.
3. WHEN the Frontend requests to read the Meeting_History, or to read, edit, or save notes
   and transcripts, THE Backend SHALL return the requested data or persist the requested
   change and return a confirmation response within 2 seconds.
4. WHILE a recording is in progress, THE Backend SHALL stream Captions and recording-status
   updates to the Frontend over the WebSocket_Channel within 2 seconds of each Caption or
   status change becoming available.
5. THE Backend SHALL invoke the existing Notes_Generator, Transcription_Service, and AWS
   logic to fulfill recording, transcription, and notes requests rather than reimplementing
   that logic.
6. IF an API request references a meeting or resource that does not exist, THEN THE Backend
   SHALL return a not-found error response that identifies the missing resource and SHALL
   leave all stored data unchanged.
7. IF the Frontend requests a recording-state transition that is invalid for the current
   state, such as pausing or stopping when no recording is in progress, THEN THE Backend
   SHALL reject the request with an error response indicating the invalid transition and
   SHALL leave the current recording state unchanged.
8. IF the Frontend requests to start recording using an Input_Device that is not in the list
   of available Input_Devices, THEN THE Backend SHALL reject the request with an error
   response indicating the Input_Device is unavailable and SHALL NOT start recording.

### Requirement 5: Recording controls and source selection in the web UI

**User Story:** As a user, I want to select my recording input device and control recording
from the web UI, so that I can run a meeting capture entirely from the browser.

#### Acceptance Criteria

1. WHEN the Frontend loads or refreshes the device list, THE Frontend SHALL display the name
   of each available Input_Device returned by the Backend, and SHALL display an empty-state
   indication when no Input_Devices are available.
2. WHEN the user selects an Input_Device, THE Backend SHALL persist that selection and SHALL
   use it for recordings until the selection is changed.
3. WHILE no recording is in progress, THE Frontend SHALL enable the start control and SHALL
   disable the pause and stop controls.
4. WHILE a recording is in progress, THE Frontend SHALL enable the pause and stop controls
   and SHALL disable the start control.
5. WHEN the user starts recording, THE Backend SHALL validate that the selected Input_Device
   exists in the current device list and is accessible for capture before capture begins.
6. IF the selected Input_Device fails validation, THEN THE Backend SHALL report the
   validation failure reason to the Frontend, SHALL NOT start recording, and SHALL retain
   the previous device selection.
7. WHEN the user pauses and later resumes a recording, THE Backend SHALL retain the audio
   captured before the pause and SHALL append audio captured after resuming to the same
   recording.
8. IF a completed recording contained audio at or below the silence amplitude threshold for
   at least 95 percent of its duration, THEN THE Backend SHALL report a silent-recording
   warning identifying the affected recording to the Frontend.

### Requirement 6: Transcription and AI model configuration in the web UI

**User Story:** As a user, I want to choose the transcription service, whisper model size,
and AI model from the web UI, so that I can control accuracy, speed, and cost.

#### Acceptance Criteria

1. THE Frontend SHALL allow the user to select the Transcription_Service from exactly the
   available options `whisper`, `aws`, and `mac`.
2. WHEN the configuration view is loaded, THE Frontend SHALL display the most recently
   applied configuration values as the pre-selected Transcription_Service, whisper model
   size, and AI model.
3. WHERE the selected Transcription_Service is `whisper`, THE Frontend SHALL allow the user
   to select the whisper model size from exactly the available options `tiny`, `base`,
   `small`, `medium`, and `large`.
4. WHERE the selected Transcription_Service is not `whisper`, THE Frontend SHALL disable
   selection of the whisper model size.
5. THE Frontend SHALL allow the user to select the AI model used for notes generation from
   the available AI model options presented by the Backend.
6. WHEN the user changes a configuration option to a value within the available options, THE
   Backend SHALL apply that selection to every transcription or notes-generation operation
   started after the change is applied.
7. IF the user submits a configuration value that is not within the available options for
   that option, THEN THE Backend SHALL reject the change, retain the most recently applied
   configuration as its active state, and THE Frontend SHALL display an error message
   indicating that the selected value is invalid.
8. WHILE a transcription or notes-generation operation is in progress, THE Backend SHALL
   continue using the configuration that was active when that operation started.
9. WHILE no configuration change is applied, THE Backend SHALL retain the most recently
   applied configuration as its active state, including across application restarts.

### Requirement 7: Notes and transcript viewing, editing, and versioning

**User Story:** As a user, I want to view, edit, save, and version meeting notes and
transcripts in the web UI, so that I retain all the document-management capabilities of the
existing desktop application.

#### Acceptance Criteria

1. THE Frontend SHALL display the Meeting_History as a list ordered by meeting start
   timestamp in descending order, with the most recent meeting appearing first.
2. WHEN the user selects a meeting from the Meeting_History, THE Frontend SHALL display the
   selected meeting's saved notes and full transcript within 3 seconds.
3. IF the user selects a meeting whose notes or transcript cannot be retrieved, THEN THE
   Frontend SHALL display an error message indicating the content could not be loaded and
   SHALL retain the Meeting_History list in its current state.
4. WHEN the user edits notes and saves them, THE Backend SHALL persist the edited notes and
   THE Frontend SHALL display a confirmation indicating the save succeeded within 3 seconds.
5. IF the user saves notes and the persistence operation fails, THEN THE Backend SHALL leave
   any previously saved Notes_Version unchanged and THE Frontend SHALL display an error
   message indicating the save failed.
6. WHEN the user saves notes for a meeting that already has at least one saved Notes_Version,
   THE Backend SHALL create a new Notes_Version and SHALL retain all previous Notes_Versions
   without modification.
7. THE Frontend SHALL allow the user to view any previously saved Notes_Version of a meeting,
   identified by its creation timestamp in descending order.
8. WHEN the user regenerates notes for a meeting, THE Notes_Generator SHALL produce the notes
   and THE Frontend SHALL display them for review without persisting them until the user
   explicitly saves.
9. IF the Notes_Generator fails to produce notes during a regeneration request, THEN THE
   Frontend SHALL display an error message indicating regeneration failed and SHALL retain
   the most recently displayed notes unchanged.

### Requirement 8: Storage and repository hygiene

**User Story:** As a user whose notes folder is synced to a git-backed Obsidian vault, I want
large recordings kept out of the vault, so that the repository does not become bloated and
git operations do not fail.

#### Acceptance Criteria

1. WHEN the Backend saves a recording, THE Backend SHALL write the recording WAV file only to
   the recordings folder, where the recordings folder resides outside the notes folder.
2. THE Backend SHALL NOT copy, move, or write recording WAV files into the notes folder.
3. WHEN the Backend generates notes or transcripts, THE Backend SHALL store the generated
   notes and transcripts in the notes folder.
4. WHERE faster-whisper models are required, THE Backend SHALL load the required model from
   the global model cache at `~/.cache/huggingface/hub`.
5. IF the global model cache is unavailable, THEN THE Backend SHALL obtain the required
   faster-whisper model by downloading it and SHALL proceed with transcription.
6. IF obtaining the required faster-whisper model fails, THEN THE Backend SHALL abort the
   transcription, SHALL present an error indicating the model could not be loaded, and SHALL
   NOT write partial notes or transcripts into the notes folder.

### Requirement 9: Coexistence with the existing desktop UI

**User Story:** As a user, I want the existing tkinter UI to keep working during the
transition, so that I can fall back to it while the web UI matures.

#### Acceptance Criteria

1. WHEN the web UI is introduced, THE existing tkinter UI SHALL launch and complete its
   startup sequence without errors, and SHALL retain all recording, transcription, and
   notes-generation functions that were available before the web UI was introduced.
2. THE Backend and the tkinter UI SHALL read from and write to the same recordings, notes,
   and transcripts storage locations.
3. WHILE both the tkinter UI and the web UI are running concurrently, THE Backend SHALL
   serialize write operations to the recordings, notes, and transcripts storage so that no
   write operation overwrites or corrupts another write operation.
4. WHEN one UI commits a change to recordings, notes, or transcripts, THE Backend SHALL make
   that change retrievable by the other UI on its next read of the affected item.
5. IF the web UI fails to start or terminates unexpectedly, THEN THE tkinter UI SHALL remain
   operable with full access to all recordings, notes, and transcripts, and SHALL present an
   indication that the web UI is unavailable.
