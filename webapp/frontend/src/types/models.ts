/**
 * Shared TypeScript types mirroring the backend data models
 * (`webapp/backend/models.py`).
 *
 * These types are the contract between the typed API client (task 15.1), the
 * caption-store reducer (task 16.1), the `useWebSocket` hook (task 17.1), and
 * the views (tasks 18-22). Keep them in sync with the Python dataclasses.
 */

// ---------------------------------------------------------------------------
// Caption
// ---------------------------------------------------------------------------

/** A caption's lifecycle status. Interim captions may be revised; final ones win. */
export type CaptionStatus = "interim" | "final";

/**
 * A single live transcription caption.
 *
 * Identity for de-duplication / replacement is the `start` timestamp (Req 1.7).
 * Captions are displayed ordered by ascending `start` (Req 1.4).
 */
export interface Caption {
  /** Seconds from recording start. De-dup identity. */
  start: number;
  /** Seconds from recording start; `end >= start`. */
  end: number;
  /** The transcribed text for this caption. */
  text: string;
  /** `"interim"` (subject to revision) or `"final"`. */
  status: CaptionStatus;
}

// ---------------------------------------------------------------------------
// SessionState
// ---------------------------------------------------------------------------

/** The recording state-machine value. */
export type RecordingStateValue = "idle" | "recording" | "paused" | "finalizing";

/**
 * Server-side recording session state surfaced to the frontend.
 * Mirrors the backend `SessionState` dataclass.
 */
export interface SessionState {
  /** The recording state-machine value. */
  state: RecordingStateValue;
  /** `YYYYMMDD_HHMMSS` id assigned at start, else `null`. */
  meeting_id: string | null;
  /** The selected input device id, else `null`. */
  device_id: number | null;
  /** Elapsed recorded (non-paused) duration in seconds. */
  duration_seconds: number;
  /** ISO-8601 start timestamp, else `null`. */
  started_at: string | null;
  /** Final-pass progress (0..100) while finalizing, else `null`. */
  final_progress: number | null;
}

// ---------------------------------------------------------------------------
// StopResult
// ---------------------------------------------------------------------------

/**
 * The outcome of stopping a recording (`POST /api/recording/stop`).
 * Mirrors the backend `StopResult` dataclass.
 */
export interface StopResult {
  /** The meeting id of the stopped recording, else `null`. */
  meeting_id: string | null;
  /** Path to the WAV file (in `recordings/` only), else `null`. */
  recording_path: string | null;
  /** True when a non-empty recording file is present (Req 2.1/2.2). */
  has_recording: boolean;
  /** True when the recording was classified as silent (Req 5.8). */
  was_silent: boolean;
  /** The peak absolute sample amplitude observed. */
  peak_amplitude: number;
}

// ---------------------------------------------------------------------------
// AppConfig
// ---------------------------------------------------------------------------

/** Allowed transcription service identifiers. */
export type TranscriptionServiceId = "whisper" | "aws" | "mac";

/** Allowed faster-whisper model sizes. */
export type WhisperModelSize = "tiny" | "base" | "small" | "medium" | "large";

/** Allowed transcription service ids as a runtime-iterable tuple (for UI controls). */
export const TRANSCRIPTION_SERVICE_IDS: readonly TranscriptionServiceId[] = [
  "whisper",
  "aws",
  "mac",
] as const;

/** Allowed whisper model sizes as a runtime-iterable tuple (for UI controls). */
export const WHISPER_MODEL_SIZES: readonly WhisperModelSize[] = [
  "tiny",
  "base",
  "small",
  "medium",
  "large",
] as const;

/**
 * The applied live/transcription/notes configuration.
 * Mirrors the backend `AppConfig` dataclass.
 */
export interface AppConfig {
  transcription_service: TranscriptionServiceId;
  whisper_model_size: WhisperModelSize;
  ai_model_id: string;
  input_device_id: number | null;
  live_window_seconds: number;
  live_overlap_seconds: number;
  final_pass_max_attempts: number;
  silence_threshold: number;
  silence_fraction_threshold: number;
}

// ---------------------------------------------------------------------------
// Device
// ---------------------------------------------------------------------------

/** An available audio input device. */
export interface Device {
  /** Device id used when starting a recording / selecting a device. */
  id: number;
  /** Human-readable device name shown in the device selector. */
  name: string;
}

// ---------------------------------------------------------------------------
// AI Model
// ---------------------------------------------------------------------------

/** An available AI model for notes generation (from `GET /api/models`). */
export interface Model {
  /** The model identifier (matches `AppConfig.ai_model_id`). */
  id: string;
  /** Human-readable model name. */
  name: string;
}

// ---------------------------------------------------------------------------
// Meeting history + versions
// ---------------------------------------------------------------------------

/** A meeting history entry. Mirrors the backend `MeetingSummary` dataclass. */
export interface MeetingSummary {
  meeting_id: string;
  display_date: string;
  title: string;
  latest_version: number;
}

/** A single saved notes version. Mirrors the backend `NotesVersion` dataclass. */
export interface NotesVersion {
  version_num: number;
  name: string;
  /** ISO-8601 creation timestamp. */
  creation_time: string;
  is_default: boolean;
}

// ---------------------------------------------------------------------------
// TranscriptResult (shared AWS-Transcribe-compatible shape)
// ---------------------------------------------------------------------------

/**
 * The shared transcript structure. Only the fields the frontend reads are
 * typed loosely here; the backend owns the full schema. The invariant is that
 * `results.transcripts[0].transcript` is a string (Req 3.1).
 */
export interface TranscriptResult {
  results: {
    transcripts: Array<{ transcript: string }>;
    items?: unknown[];
    speaker_labels?: unknown;
  };
  [key: string]: unknown;
}
