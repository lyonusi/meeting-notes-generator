/**
 * Zustand application store (scaffold).
 *
 * This defines the *shape* of the global app state and a minimal set of plain
 * setters so later tasks have a place to land:
 *
 * - The caption-store reducer (task 16.1) will replace `applyCaption` /
 *   `applyChunkError` with the pure ordering/de-dup/latest-wins logic
 *   (Property 1). For the scaffold, captions are held as an ordered array
 *   keyed conceptually by `start`; no reducer logic is implemented here.
 * - The typed API client (task 15.1) will call the config/devices/meetings
 *   setters after fetching from the backend.
 * - The `useWebSocket` hook (task 17.1) will drive `setSessionState`,
 *   `replaceCaptions` (replay), and the caption setters.
 *
 * Keep the state fields aligned with the design's "State management" section:
 * `recordingState`, `captions`, `config`, `devices`, `meetings`, and the
 * currently open document/version.
 */

import { create } from "zustand";
import type {
  AppConfig,
  Caption,
  Device,
  MeetingSummary,
  Model,
  NotesVersion,
  SessionState,
} from "../types";
import {
  applyCaption as reduceApplyCaption,
  applyChunkError as reduceApplyChunkError,
  clearCaptions as reduceClearCaptions,
  replaceCaptions as reduceReplaceCaptions,
  type ChunkError,
} from "./captionReducer";

/** The currently open notes/transcript document for the document view. */
export interface OpenDocument {
  /** The meeting whose document is open. */
  meeting_id: string;
  /** The selected notes version, or `null` for the latest/default. */
  version: NotesVersion | null;
  /** All versions available for the meeting (descending by creation time). */
  versions: NotesVersion[];
  /** The loaded notes markdown content, or `null` if not yet loaded. */
  notes: string | null;
  /** The loaded transcript text, or `null` if not yet loaded. */
  transcript: string | null;
}

/** The default idle session state used before the backend reports otherwise. */
export const INITIAL_SESSION_STATE: SessionState = {
  state: "idle",
  meeting_id: null,
  device_id: null,
  duration_seconds: 0,
  started_at: null,
  final_progress: null,
};

/** The full application state shape. */
export interface AppState {
  // --- Recording / session ------------------------------------------------
  /** Current server-owned recording session state. */
  recordingState: SessionState;

  // --- Live captions ------------------------------------------------------
  /**
   * Ordered, de-duplicated captions keyed by `start`.
   *
   * Maintained by the pure caption reducer (`captionReducer.ts`, task 16.1),
   * which enforces ascending-`start` ordering, uniqueness, and latest-wins
   * (final supersedes interim at the same `start`). Views read this directly.
   */
  captions: Caption[];

  /**
   * The most recent chunk-processing error, or `null`. Surfaced inline by the
   * live view; recording it never removes displayed captions (Req 1.9).
   */
  captionError: ChunkError | null;

  // --- Configuration ------------------------------------------------------
  /** The applied configuration, or `null` until loaded from the backend. */
  config: AppConfig | null;
  /** Available AI models for notes generation. */
  models: Model[];

  // --- Devices ------------------------------------------------------------
  /** Available audio input devices (may be empty). */
  devices: Device[];

  // --- Meeting history ----------------------------------------------------
  /** Meeting history (descending by start timestamp). */
  meetings: MeetingSummary[];

  // --- Open document / version -------------------------------------------
  /** The currently open notes/transcript document, or `null` if none. */
  openDocument: OpenDocument | null;

  // --- Connectivity -------------------------------------------------------
  /** Whether the backend is currently reachable (surfaced by api client / ws). */
  backendAvailable: boolean;

  // --- Actions (scaffold setters) ----------------------------------------
  setSessionState: (state: SessionState) => void;
  /** Replace the entire caption list (used for WS replay on (re)connect). */
  replaceCaptions: (captions: Caption[]) => void;
  /**
   * Apply a single caption event via the pure reducer: insert or replace by
   * `start`, keeping ascending order, uniqueness, and latest-wins.
   */
  applyCaption: (caption: Caption) => void;
  /**
   * Apply a chunk-error event: records the latest error for inline display
   * while retaining all already-displayed captions (Req 1.9).
   */
  applyChunkError: (chunkId: string, message: string) => void;
  clearCaptions: () => void;

  setConfig: (config: AppConfig) => void;
  setModels: (models: Model[]) => void;
  setDevices: (devices: Device[]) => void;
  setMeetings: (meetings: MeetingSummary[]) => void;

  setOpenDocument: (doc: OpenDocument | null) => void;
  setBackendAvailable: (available: boolean) => void;
}

/** The global Zustand store hook. */
export const useAppStore = create<AppState>((set) => ({
  recordingState: INITIAL_SESSION_STATE,
  captions: [],
  captionError: null,
  config: null,
  models: [],
  devices: [],
  meetings: [],
  openDocument: null,
  backendAvailable: true,

  setSessionState: (state) => set({ recordingState: state }),

  replaceCaptions: (captions) =>
    set((s) => {
      const next = reduceReplaceCaptions(
        { captions: s.captions, lastError: s.captionError },
        captions,
      );
      return { captions: next.captions, captionError: next.lastError };
    }),

  applyCaption: (caption) =>
    set((s) => {
      const next = reduceApplyCaption(
        { captions: s.captions, lastError: s.captionError },
        caption,
      );
      return { captions: next.captions, captionError: next.lastError };
    }),

  // Retains captions (Req 1.9); records the latest chunk error for the UI.
  applyChunkError: (chunkId, message) =>
    set((s) => {
      const next = reduceApplyChunkError(
        { captions: s.captions, lastError: s.captionError },
        { chunkId, message },
      );
      return { captions: next.captions, captionError: next.lastError };
    }),

  clearCaptions: () =>
    set((s) => {
      const next = reduceClearCaptions({
        captions: s.captions,
        lastError: s.captionError,
      });
      return { captions: next.captions, captionError: next.lastError };
    }),

  setConfig: (config) => set({ config }),
  setModels: (models) => set({ models }),
  setDevices: (devices) => set({ devices }),
  setMeetings: (meetings) => set({ meetings }),

  setOpenDocument: (openDocument) => set({ openDocument }),
  setBackendAvailable: (backendAvailable) => set({ backendAvailable }),
}));
