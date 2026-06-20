/**
 * Settings tab for the Meeting Notes Generator plugin.
 */

import { App, PluginSettingTab, Setting } from "obsidian";
import type MeetingNotesPlugin from "./main";
import type { WhisperModelSize } from "./types";

export class MeetingNotesSettingTab extends PluginSettingTab {
  private plugin: MeetingNotesPlugin;

  constructor(app: App, plugin: MeetingNotesPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Meeting Notes Generator" });

    new Setting(containerEl)
      .setName("Notes folder")
      .setDesc("Vault-relative folder where generated notes are saved.")
      .addText((text) =>
        text
          .setPlaceholder("Meeting Notes")
          .setValue(this.plugin.settings.notesFolder)
          .onChange(async (value) => {
            this.plugin.settings.notesFolder = value.trim() || "Meeting Notes";
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Whisper model")
      .setDesc("Local transcription model (larger = more accurate, slower).")
      .addDropdown((dd) =>
        dd
          .addOption("tiny", "Tiny (fastest)")
          .addOption("base", "Base (recommended)")
          .addOption("small", "Small (most accurate)")
          .setValue(this.plugin.settings.whisperModel)
          .onChange(async (value) => {
            this.plugin.settings.whisperModel = value as WhisperModelSize;
            await this.plugin.saveSettings();
          }),
      );

    containerEl.createEl("h3", { text: "AWS Bedrock (notes generation)" });

    new Setting(containerEl)
      .setName("AWS region")
      .setDesc("Region for the Bedrock endpoint.")
      .addText((text) =>
        text
          .setPlaceholder("us-west-2")
          .setValue(this.plugin.settings.awsRegion)
          .onChange(async (value) => {
            this.plugin.settings.awsRegion = value.trim() || "us-west-2";
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("AWS profile")
      .setDesc("Named profile in ~/.aws to use for Bedrock. Leave blank for the default chain.")
      .addText((text) =>
        text
          .setPlaceholder("bedrock")
          .setValue(this.plugin.settings.awsProfile)
          .onChange(async (value) => {
            this.plugin.settings.awsProfile = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Bedrock model id")
      .setDesc("An active Claude model id (deprecated models are rejected by Bedrock).")
      .addText((text) =>
        text
          .setPlaceholder("anthropic.claude-sonnet-4-5-20250929-v1:0")
          .setValue(this.plugin.settings.bedrockModelId)
          .onChange(async (value) => {
            this.plugin.settings.bedrockModelId =
              value.trim() || "anthropic.claude-sonnet-4-5-20250929-v1:0";
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Save transcript")
      .setDesc("Also save the raw transcript in the note.")
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.saveTranscript)
          .onChange(async (value) => {
            this.plugin.settings.saveTranscript = value;
            await this.plugin.saveSettings();
          }),
      );
  }
}
