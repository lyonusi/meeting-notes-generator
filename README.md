# Meeting Notes Generator

A macOS application that records audio during meetings and automatically generates
structured meeting notes. It ships with **two interfaces** that share the same storage:

1. **Web UI** (recommended) — a modern browser app with **live transcription** while you
   record, backed by a FastAPI server. See [Web UI](#web-ui-recommended).
2. **Desktop UI** — the original tkinter application. See [Desktop UI (tkinter)](#desktop-ui-tkinter).

## Features

- Record audio from a microphone or system output (via a loopback device) during meetings
- **Live transcription** — see captions stream in while you record (web UI)
- Transcribe meetings using local Whisper (faster-whisper), AWS Transcribe, or macOS speech
- Generate structured meeting notes using AWS Bedrock (Anthropic Claude)
- Store meeting notes and full transcripts
- Start, pause, resume, and stop recordings with input-device validation and
  silent-recording detection
- Retry transcription with different services; regenerate notes with different AI models
- **Version management** for notes: multiple versions per meeting, default version,
  side-by-side diff (desktop UI), version selector (web UI)
- Both UIs read/write the same `notes/` and `recordings/` folders, so you can switch freely

## Architecture

```
main.py            → Desktop (tkinter) entry point
webapp/backend/    → FastAPI server (HTTP + WebSocket) wrapping the core modules
webapp/frontend/   → React + Tailwind single-page app (the web UI)

Shared core modules (used by both UIs):
  audio_capture.py        → AudioRecorder (device selection, capture, silence detection)
  transcription.py        → Whisper / AWS / macOS transcription services
  notes_generator.py      → notes generation via AWS Bedrock
  aws_services.py         → Bedrock + Transcribe + S3 helpers
  version_manager.py      → notes/transcript versioning + metadata
  config.py               → AWS region, model ids, audio + transcription settings
```

The web backend is a thin orchestration layer: it reuses the existing core modules rather
than reimplementing them, so behaviour stays consistent between the two UIs.

## Requirements

- Python 3.9+ (3.13 tested)
- Node.js 18+ and npm (only for the web UI frontend)
- For AWS services (optional, needed for notes generation):
  - AWS Account with access to:
    - AWS Bedrock (with Anthropic Claude models enabled) — for notes generation
    - AWS Transcribe + Amazon S3 — only if you use the `aws` transcription service
  - Valid AWS credentials
  - An **active** Claude model (deprecated/"Legacy" models are rejected by Bedrock; set
    an active model id in `config.py` / the web UI Configuration panel)
- For local transcription (no AWS needed):
  - faster-whisper / openai-whisper (included in requirements.txt); models download to
    `~/.cache/huggingface/hub` on first use

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/lyonusi/meeting-notes-generator.git
cd meeting-notes-generator
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

**Note for macOS users:** Installing PyAudio might require additional steps:

```bash
brew install portaudio
pip install pyaudio
```

### 3. Configure AWS credentials

Ensure your AWS credentials are configured in one of the following ways:

- `~/.aws/credentials` file:
  ```
  [default]
  aws_access_key_id = YOUR_ACCESS_KEY
  aws_secret_access_key = YOUR_SECRET_KEY
  
  [bedrock]
  aws_access_key_id = YOUR_BEDROCK_ACCESS_KEY
  aws_secret_access_key = YOUR_BEDROCK_SECRET_KEY
  ```
- Environment variables:
  ```bash
  export AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
  export AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
  ```

**Note:** The application uses separate profiles for different AWS services. By default, it uses the "default" profile for S3 and Transcribe, and the "bedrock" profile for AWS Bedrock API calls. You can modify this in the code if needed.

### 4. Configure the application

Edit the `config.py` file to customize your settings:
- AWS region
- S3 bucket name
- Bedrock model selection
- Audio settings

## Recording System Audio on macOS

To capture system audio on macOS, you'll need a virtual audio device:

1. Install BlackHole (a free virtual audio driver):
   ```bash
   brew install blackhole-2ch
   ```

2. Set up Multi-Output Device in Audio MIDI Setup:
   - Open "Audio MIDI Setup" (use Spotlight to find it)
   - Click the "+" button in the bottom left and select "Create Multi-Output Device"
   - Check both your speakers and "BlackHole 2ch"
   - Select the Multi-Output Device as your system output in System Preferences > Sound

3. In the Meeting Notes Generator app:
   - Select "BlackHole 2ch" as your input device

## Web UI (recommended)

The web UI runs as a local FastAPI backend plus a React frontend. It adds **live
transcription** (captions stream while you record) and a cleaner two-page interface:

- **Record** — device selection, start/pause/stop, live captions; a ⚙ Settings drawer
  holds transcription/model configuration.
- **Meetings** — a master–detail view: meeting list on the left, the selected meeting's
  notes + transcript on the right, with a "Generate Notes" / "Regenerate" action and a
  version selector.

### Start the backend

```bash
cd meeting-notes-generator
# from the project root, with the venv active / deps installed:
python -m uvicorn webapp.backend.app:app --reload
# serves on http://127.0.0.1:8000  (use --port 8077 if 8000 is taken)
```

### Start the frontend

```bash
cd webapp/frontend
npm install          # first time only
npm run dev          # serves the UI (Vite prints the URL, e.g. http://localhost:5173)
```

The Vite dev server proxies `/api` and `/ws` to the backend, so just open the printed
URL. For a production build: `npm run build` (output in `webapp/frontend/dist/`, which the
backend will serve at `/` if present).

### Typical flow

1. Open the UI, go to **Record**, pick your input device (see
   [Recording System Audio on macOS](#recording-system-audio-on-macos) to capture meeting
   audio), and click **Start**. Captions stream live.
2. Click **Stop** — a full accurate transcription pass runs and becomes the authoritative
   transcript.
3. Go to **Meetings**, select the meeting, click **Generate Notes**, then **Save** to keep
   them as a version. Edit and re-save to create further versions.

> Notes generation requires AWS Bedrock with an active Claude model. Live captions and the
> final transcript use local Whisper and need no AWS.

## Usage

### Desktop UI (tkinter)

Start the application:

```bash
cd meeting-notes-generator
python main.py
```

For debugging:
```bash
python main.py --debug
```

### Recording a meeting

1. Select your input device from the dropdown
2. Click "Start" to begin recording
3. Use "Pause" and "Resume" as needed
4. Click "Stop" when the meeting ends
5. Wait for processing to complete

### Working with notes

- View generated notes in the right panel
- Save notes to a specific location using "Save Notes As..."
- Copy notes to clipboard using "Copy to Clipboard"
- View the full transcript by clicking "View Transcript"
- Edit notes directly in the interface and save with Ctrl+S/⌘S

### Previous recordings

- Access previous recordings from the "Previous Recordings" section
- Double-click any entry to open it
- Select multiple items for batch operations
- Use keyboard shortcuts (Delete/Backspace) for quick deletion

### Using the Version Management System

The version management system allows you to track and compare different versions of transcripts and notes for the same meeting:

1. **Accessing Versions**:
   - Click on a meeting in the list to select it
   - Navigate to the "Versions" tab in the right panel
   - All versions of the selected meeting will be displayed

2. **Comparing Versions**:
   - Select two versions in the list (hold Ctrl/⌘ for multiple selection)
   - Click "Compare Selected" to view a side-by-side comparison
   - The comparison view shows both versions and highlights differences

3. **Managing Versions**:
   - Right-click on a version for additional options:
     - Set as Default: Mark a version as the default version
     - Rename Version: Give the version a custom name
     - Add Comments: Add notes or context about this version
     - Compare with Default: Compare with the current default version
     - Delete Version: Remove a version from history

4. **Timeline View**:
   - Click "View Timeline" to see a visual representation of version history
   - The timeline shows when each version was created and which tools were used

5. **Creating New Versions**:
   - Use the "Regenerate Notes" button to create a new version with different AI models
   - Use the "Retranscribe" button to create a new version with different transcription services
   - Version numbers (_v2, _v3, etc.) are automatically assigned

## AWS Bedrock Inference Profiles

Newer Claude models (like Claude Sonnet 4 and Claude 3.7) require inference profiles in AWS Bedrock. This application supports dynamic inference profile handling:

### What are Inference Profiles?

Inference profiles in AWS Bedrock provide dedicated throughput for foundation models. They're required for newer Claude models and ensure stable API access.

### Setting up Inference Profiles

1. In your AWS Bedrock console, navigate to "Inference profiles"
2. Click "Create inference profile"
3. Select the model (e.g., "Claude Sonnet 4")
4. Choose your provisioned throughput settings
5. Complete the creation process

### Testing Inference Profiles

Use the included test script to verify your inference profile setup:

```bash
python test_inference_profile.py
```

This script will:
- List all available inference profiles in your account
- Check if a profile exists for the model in your config
- Test a simple generation task using the profile

You can specify a different AWS profile or model:

```bash
python test_inference_profile.py --profile my-aws-profile --model anthropic.claude-sonnet-4-20250514-v1:0
```

### Dynamic Profile ARN Construction

The application attempts to dynamically construct profile ARNs if no matching profile is found in your account. This works if:

1. You have the same model enabled in different AWS accounts
2. The inference profile follows the standard naming pattern 

## Running the Demo

The included demo script provides a quick way to test the functionality:

```bash
python demo.py --file path/to/audio_file.wav
```

This will process the audio file, generate a transcript and notes, and save them to the notes directory.

Add the `--show-versions` flag to demonstrate the version management features:

```bash
python demo.py --file path/to/audio_file.wav --show-versions
```

## Local Notes Generation Options

While the application primarily uses AWS Bedrock for AI-powered meeting notes generation, you can explore these free, open-source alternatives:

### Free Local AI Models

For notes generation without external services, consider:

1. **LLama CPP** - Quantized models can run on most hardware:
   - Llama-2-7B or Mistral-7B variants for basic notes
   - Requires additional integration (not currently built-in)
   - https://github.com/ggerganov/llama.cpp

2. **Ollama** - Easy to use interface for running models locally:
   - Supports various models like Llama, Mistral, and more
   - Simple API for integration
   - https://github.com/ollama/ollama

3. **GPT4All** - Lightweight local model:
   - Optimized for personal computers
   - Python bindings available
   - https://github.com/nomic-ai/gpt4all

## Future Enhancements

- Automatic meeting detection (for common meeting apps)
- Meeting app integration
- Enhanced audio processing
- Integrated local AI models support (notes generation without AWS)
- Version merging capabilities and exportable version-history reports
- Cloud synchronization of version metadata
- **Obsidian plugin** packaging (see [Running inside Obsidian](#running-inside-obsidian))

## Running inside Obsidian

The `notes/` and `recordings/` folders are typically symlinked into an Obsidian vault, so
generated notes already show up in Obsidian. Tighter integration (a true plugin) is
possible — see the options and tradeoffs below.

**Quick win (works today):** keep `notes/` symlinked into your vault and run the web UI
alongside Obsidian. Generated `.md` notes appear in the vault automatically. Recordings
(`.wav`) are kept out of the vault's git to avoid bloat.

**Companion plugin (recommended next step):** a thin Obsidian plugin that talks to the
existing FastAPI backend over HTTP/WebSocket and renders the UI in a custom view —
reusing all current backend logic. The Python backend runs as a local helper process.

**Full native plugin:** re-implement capture/transcription in TypeScript/WASM to drop the
Python dependency. Most work; only needed for a distributable community plugin.

## License

[MIT License](LICENSE)
