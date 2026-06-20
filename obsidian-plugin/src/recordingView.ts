/**
 * The Meeting Notes recording panel — an Obsidian ItemView in the right
 * sidebar. Hosts device selection, record controls, a live caption stream, and
 * the post-recording generate/save flow.
 */

import { ItemView, Notice, WorkspaceLeaf, normalizePath, TFile } from "obsidian";
import type MeetingNotesPlugin from "./main";
import { Recorder, type InputDevice } from "./recorder";
import { Transcriber } from "./transcriber";
import { NotesGenerator } from "./notesGenerator";
import type { Caption } from "./types";

export const VIEW_TYPE_MEETING_NOTES = "meeting-notes-recorder";

type RecState = "idle" | "recording" | "paused" | "processing";

export class RecordingView extends ItemView {
  private plugin: MeetingNotesPlugin;
  private recorder = new Recorder();
  private transcriber: Transcriber;

  private state: RecState = "idle";
  private captions: Caption[] = [];
  private startedAt: Date | null = null;

  // UI refs
  private deviceSelect!: HTMLSelectElement;
  private statusEl!: HTMLElement;
  private captionsEl!: HTMLElement;
  private startBtn!: HTMLButtonElement;
  private pauseBtn!: HTMLButtonElement;
  private stopBtn!: HTMLButtonElement;

  constructor(leaf: WorkspaceLeaf, plugin: MeetingNotesPlugin) {
    super(leaf);
    this.plugin = plugin;
    this.transcriber = new Transcriber(plugin.settings.whisperModel);
  }

  getViewType(): string {
    return VIEW_TYPE_MEETING_NOTES;
  }

  getDisplayText(): string {
    return "Meeting Notes";
  }

  getIcon(): string {
    return "mic";
  }

  async onOpen(): Promise<void> {
    const root = this.contentEl;
    root.empty();
    root.addClass("mng-view");

    root.createEl("h3", { text: "Meeting Notes" });

    // Device selector
    const deviceRow = root.createDiv({ cls: "mng-row" });
    deviceRow.createEl("label", { text: "Input device" });
    this.deviceSelect = deviceRow.createEl("select");
    await this.populateDevices();

    // Controls
    const controls = root.createDiv({ cls: "mng-controls" });
    this.startBtn = controls.createEl("button", { text: "● Start" });
    this.startBtn.addClass("mod-cta");
    this.pauseBtn = controls.createEl("button", { text: "Pause" });
    this.stopBtn = controls.createEl("button", { text: "Stop" });

    this.startBtn.onclick = () => void this.handleStart();
    this.pauseBtn.onclick = () => this.handlePauseResume();
    this.stopBtn.onclick = () => void this.handleStop();

    // Status
    this.statusEl = root.createDiv({ cls: "mng-status" });

    // Captions
    root.createEl("h4", { text: "Transcript" });
    this.captionsEl = root.createDiv({ cls: "mng-captions" });

    this.renderState();
  }

  async onClose(): Promise<void> {
    if (this.recorder.isRecording) {
      await this.recorder.stop();
    }
  }

  // ------------------------------------------------------------------
  // Device handling
  // ------------------------------------------------------------------

  private async populateDevices(): Promise<void> {
    this.deviceSelect.empty();
    let devices: InputDevice[] = [];
    try {
      // A getUserMedia grant is needed for device labels; request once.
      const tmp = await navigator.mediaDevices.getUserMedia({ audio: true });
      tmp.getTracks().forEach((t) => t.stop());
      devices = await Recorder.listInputDevices();
    } catch {
      // Permission not granted yet — leave a placeholder.
    }
    if (devices.length === 0) {
      const opt = this.deviceSelect.createEl("option", {
        text: "Default input",
      });
      opt.value = "";
      return;
    }
    for (const d of devices) {
      const opt = this.deviceSelect.createEl("option", { text: d.label });
      opt.value = d.id;
    }
  }

  // ------------------------------------------------------------------
  // Recording lifecycle
  // ------------------------------------------------------------------

  private async handleStart(): Promise<void> {
    if (this.state === "paused") {
      this.recorder.resume();
      this.state = "recording";
      this.renderState();
      return;
    }
    if (this.state !== "idle") return;

    this.captions = [];
    this.captionsEl.empty();
    try {
      // Warm up the model while/before capture begins.
      void this.transcriber.load((msg) => this.setStatus(msg));
      await this.recorder.start(this.deviceSelect.value || undefined);
    } catch (err) {
      new Notice(`Could not start recording: ${errMessage(err)}`);
      return;
    }
    this.startedAt = new Date();
    this.state = "recording";
    // NOTE: We intentionally do NOT run a live windowing loop. Whisper WASM
    // inference runs on the main thread and blocks Obsidian's UI; re-running it
    // every few seconds stacks passes and freezes the app. Instead we capture
    // audio silently and run a single transcription pass when the user stops.
    this.renderState();
  }

  private handlePauseResume(): void {
    if (this.state === "recording") {
      this.recorder.pause();
      this.state = "paused";
    } else if (this.state === "paused") {
      this.recorder.resume();
      this.state = "recording";
    }
    this.renderState();
  }

  private async handleStop(): Promise<void> {
    if (this.state !== "recording" && this.state !== "paused") return;
    this.state = "processing";
    this.renderState();
    this.setStatus("Finalizing transcript… (this may take a moment)");

    let audio: Float32Array;
    try {
      audio = await this.recorder.stop();
    } catch (err) {
      new Notice(`Recording failed: ${errMessage(err)}`);
      this.resetIdle();
      return;
    }

    if (audio.length === 0) {
      new Notice("No audio was captured.");
      this.resetIdle();
      return;
    }

    // Full, accurate final transcription pass over the whole recording.
    let finalCaptions: Caption[] = [];
    try {
      finalCaptions = await this.transcriber.transcribe(audio, 0, "final");
    } catch (err) {
      new Notice(`Transcription failed: ${errMessage(err)}`);
      this.resetIdle();
      return;
    }
    this.captions = finalCaptions;
    this.renderCaptions();

    const transcript = this.captions.map((c) => c.text).join(" ").trim();
    if (!transcript) {
      new Notice("Transcript was empty — nothing to save.");
      this.resetIdle();
      return;
    }

    // Generate notes via Bedrock (optional — save transcript regardless).
    this.setStatus("Generating notes with Bedrock…");
    let notes: string | null = null;
    try {
      const generator = new NotesGenerator(this.plugin.settings);
      notes = await generator.generate(transcript);
    } catch (err) {
      new Notice(`Notes generation failed: ${errMessage(err)}. Saving transcript only.`);
      notes = null;
    }

    try {
      const file = await this.saveNote(transcript, notes);
      new Notice(`Saved: ${file.path}`);
      await this.app.workspace.getLeaf(false).openFile(file);
    } catch (err) {
      new Notice(`Could not save note: ${errMessage(err)}`);
    }

    this.resetIdle();
  }

  // ------------------------------------------------------------------
  // Saving
  // ------------------------------------------------------------------

  private async saveNote(transcript: string, notes: string | null): Promise<TFile> {
    const folder = this.plugin.settings.notesFolder;
    await this.ensureFolder(folder);

    const stamp = formatStamp(this.startedAt ?? new Date());
    const path = normalizePath(`${folder}/Meeting ${stamp}.md`);

    const parts: string[] = [];
    parts.push(`# Meeting Notes — ${stamp}`, "");
    if (notes) {
      parts.push(notes, "");
    } else {
      parts.push("> Notes generation unavailable. Transcript saved below.", "");
    }
    if (this.plugin.settings.saveTranscript) {
      parts.push("## Transcript", "", transcript, "");
    }
    const content = parts.join("\n");

    const existing = this.app.vault.getAbstractFileByPath(path);
    if (existing instanceof TFile) {
      await this.app.vault.modify(existing, content);
      return existing;
    }
    return this.app.vault.create(path, content);
  }

  private async ensureFolder(folder: string): Promise<void> {
    const normalized = normalizePath(folder);
    if (!this.app.vault.getAbstractFileByPath(normalized)) {
      await this.app.vault.createFolder(normalized).catch(() => {
        /* already exists / race — ignore */
      });
    }
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------

  private resetIdle(): void {
    this.state = "idle";
    this.startedAt = null;
    this.renderState();
  }

  private setStatus(text: string): void {
    this.statusEl.setText(text);
  }

  private renderState(): void {
    const recording = this.state === "recording";
    const paused = this.state === "paused";
    const processing = this.state === "processing";

    this.startBtn.disabled = recording || processing;
    this.startBtn.setText(paused ? "Resume" : "● Start");
    this.pauseBtn.disabled = !(recording || paused);
    this.pauseBtn.setText(paused ? "Resume" : "Pause");
    this.stopBtn.disabled = !(recording || paused);
    this.deviceSelect.disabled = recording || paused || processing;

    const labels: Record<RecState, string> = {
      idle: "Idle",
      recording: "● Recording… (transcribes when you press Stop)",
      paused: "Paused",
      processing: "Processing…",
    };
    this.setStatus(labels[this.state]);
  }

  private renderCaptions(): void {
    this.captionsEl.empty();
    if (this.captions.length === 0) {
      this.captionsEl.createEl("p", {
        text: "The transcript will appear here after you press Stop.",
        cls: "mng-empty",
      });
      return;
    }
    for (const cap of this.captions) {
      const line = this.captionsEl.createDiv({ cls: "mng-caption" });
      if (cap.status === "interim") line.addClass("mng-interim");
      line.setText(cap.text);
    }
    this.captionsEl.scrollTop = this.captionsEl.scrollHeight;
  }
}

function formatStamp(date: Date): string {
  const pad = (n: number) => n.toString().padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}.${pad(date.getMinutes())}.${pad(date.getSeconds())}`
  );
}

function errMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}
