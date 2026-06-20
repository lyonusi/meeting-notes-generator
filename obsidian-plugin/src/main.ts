/**
 * Meeting Notes Generator — Obsidian plugin entry point.
 *
 * Registers a right-sidebar recording view, a ribbon icon, and a command to
 * open it, plus the settings tab. All recording, transcription (local Whisper
 * WASM) and notes generation (AWS Bedrock) run inside Obsidian — no external
 * Python backend.
 */

import { Plugin, WorkspaceLeaf } from "obsidian";
import { DEFAULT_SETTINGS, type MeetingNotesSettings } from "./types";
import { MeetingNotesSettingTab } from "./settingsTab";
import { RecordingView, VIEW_TYPE_MEETING_NOTES } from "./recordingView";

export default class MeetingNotesPlugin extends Plugin {
  settings: MeetingNotesSettings = DEFAULT_SETTINGS;

  async onload(): Promise<void> {
    await this.loadSettings();

    this.registerView(
      VIEW_TYPE_MEETING_NOTES,
      (leaf: WorkspaceLeaf) => new RecordingView(leaf, this),
    );

    this.addRibbonIcon("mic", "Meeting Notes: record", () => {
      void this.activateView();
    });

    this.addCommand({
      id: "open-meeting-notes-recorder",
      name: "Open recording panel",
      callback: () => void this.activateView(),
    });

    this.addSettingTab(new MeetingNotesSettingTab(this.app, this));
  }

  onunload(): void {
    // Obsidian detaches our leaves automatically; nothing else to clean up.
  }

  /** Reveal the recording view in the right sidebar (creating it if needed). */
  async activateView(): Promise<void> {
    const { workspace } = this.app;
    const existing = workspace.getLeavesOfType(VIEW_TYPE_MEETING_NOTES);
    if (existing.length > 0) {
      workspace.revealLeaf(existing[0]);
      return;
    }
    const leaf = workspace.getRightLeaf(false);
    if (leaf) {
      await leaf.setViewState({ type: VIEW_TYPE_MEETING_NOTES, active: true });
      workspace.revealLeaf(leaf);
    }
  }

  async loadSettings(): Promise<void> {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }
}
