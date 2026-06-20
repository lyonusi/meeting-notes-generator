# Meeting Notes Generator — Obsidian Plugin (native)

A fully native Obsidian plugin (TypeScript) that records a meeting, transcribes it
**locally with Whisper running in WASM** (via transformers.js), and generates structured
notes with **AWS Bedrock** — all inside Obsidian, with no Python backend.

This is the "Option B" native build that lives alongside the FastAPI web app in the parent
repo. It writes notes straight into your vault.

## Features

- Record from any audio input device (mic; system/meeting audio via a loopback device such
  as BlackHole on macOS).
- Live-ish captions during recording (rolling Whisper windows) plus an accurate final pass
  on stop.
- Notes generation via AWS Bedrock (Anthropic Claude) using your `~/.aws` credentials.
- Saves a Markdown note (notes + optional transcript) into a configurable vault folder.

## Build

```bash
cd obsidian-plugin
npm install
npm run build      # produces main.js
# for development with rebuild-on-save:
npm run dev
```

## Install into a vault

Copy (or symlink) `manifest.json`, `main.js`, and `styles.css` into:

```
<your-vault>/.obsidian/plugins/meeting-notes-generator/
```

Then enable "Meeting Notes Generator" in Obsidian → Settings → Community plugins.

## Configure

Open the plugin settings:
- **Notes folder** — where notes are saved (default `Meeting Notes`).
- **Whisper model** — `tiny` / `base` / `small` (downloaded once, cached in-browser).
- **AWS region / profile / Bedrock model id** — for notes generation. Use an **active**
  Claude model id (deprecated/Legacy models are rejected by Bedrock).

## Use

1. Click the microphone ribbon icon (or run "Meeting Notes: Open recording panel").
2. Pick an input device, click **Start**. Captions stream as you talk.
3. Click **Stop** — the final transcript is produced and notes are generated; a Markdown
   note opens in your vault.

## Notes / limitations

- **Desktop only** (uses Web Audio + WASM in Electron).
- Capturing the other side of a video call requires routing system audio into a loopback
  input device, the same as the desktop app.
- First recording downloads the Whisper model (tens to hundreds of MB depending on size).
- Notes generation needs valid AWS credentials with Bedrock access to an active model.
