# Meeting Notes Generator

A macOS application that records audio during meetings and automatically generates structured meeting notes.

## Features

- Record audio from both microphone and system output during meetings
- Transcribe meetings using AWS Transcribe or local Whisper
- Generate structured meeting notes using AWS Bedrock
- Store meeting notes and full transcripts
- Simple UI to start, pause, resume, and stop recordings
- Retry transcription if it fails with different services
- Regenerate notes with different AI models

## Requirements

- Python 3.7+
- For AWS services (optional):
  - AWS Account with access to:
    - AWS Transcribe
    - AWS Bedrock
    - Amazon S3
  - Valid AWS credentials
- For local transcription:
  - OpenAI Whisper (included in requirements.txt)
  - faster-whisper (included in requirements.txt)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/meeting-notes-generator.git
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
  ```
- Environment variables:
  ```bash
  export AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
  export AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
  ```

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

## Usage

### Starting the application

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

### Previous recordings

- Access previous recordings from the "Previous Recordings" section
- Double-click any entry to open it

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
- Real-time transcription and notes
- Meeting app integration
- Native macOS app with improved UI
- Enhanced audio processing
- Integrated local AI models support

## License

[MIT License](LICENSE)
