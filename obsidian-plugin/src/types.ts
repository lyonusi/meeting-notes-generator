/**
 * Shared types for the Meeting Notes Generator Obsidian plugin.
 */

/** A single transcription caption segment. */
export interface Caption {
  /** Start offset in seconds from the beginning of the recording. */
  start: number;
  /** End offset in seconds; `end >= start`. */
  end: number;
  /** The transcribed text for this segment. */
  text: string;
  /** `"interim"` segments may still be revised; `"final"` are committed. */
  status: "interim" | "final";
}

/** Whisper model sizes supported by the in-browser (transformers.js) engine. */
export type WhisperModelSize = "tiny" | "base" | "small";

/** Persisted plugin settings. */
export interface MeetingNotesSettings {
  /** Folder (vault-relative) where generated notes are written. */
  notesFolder: string;
  /** Whisper model size used for local transcription. */
  whisperModel: WhisperModelSize;
  /** AWS region for Bedrock. */
  awsRegion: string;
  /** Bedrock model id used for notes generation. */
  bedrockModelId: string;
  /**
   * AWS credentials profile name to use (read from ~/.aws). When set, the
   * plugin uses the shared credentials file via the AWS SDK default provider
   * chain. Leave blank to use the environment/default chain.
   */
  awsProfile: string;
  /** Whether to also save the raw transcript alongside the notes. */
  saveTranscript: boolean;
}

/** Default settings applied on first install. */
export const DEFAULT_SETTINGS: MeetingNotesSettings = {
  notesFolder: "Meeting Notes",
  whisperModel: "base",
  awsRegion: "us-west-2",
  bedrockModelId: "anthropic.claude-sonnet-4-5-20250929-v1:0",
  awsProfile: "bedrock",
  saveTranscript: true,
};
