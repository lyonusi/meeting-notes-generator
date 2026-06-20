/**
 * Pure caption-store reducer (task 16.1).
 *
 * This module is intentionally framework-free: it has **no React and no
 * Zustand dependency** so the fast-check property test (task 16.2) can exercise
 * it directly, and the Zustand store (`store.ts`) can call into it.
 *
 * Captions are an ordered, de-duplicated collection keyed by their `start`
 * timestamp (design "Caption handling"). The reducer enforces three invariants
 * for any sequence of events (Property 1):
 *
 *  1. The displayed list is sorted by ascending `start` (Req 1.4).
 *  2. There are no two captions with the same `start` — a same-`start` arrival
 *     replaces the prior one according to the precedence rules below (Req 1.7).
 *  3. Applying a chunk-error never removes any already-displayed caption
 *     (Req 1.9).
 *
 * ### Same-`start` precedence (latest-wins, final-protected)
 *
 * When an incoming caption has the same `start` as an existing one:
 *
 *  | existing \ incoming | interim                         | final                       |
 *  |---------------------|---------------------------------|-----------------------------|
 *  | interim             | REPLACE (interim revision)      | REPLACE (final supersedes)  |
 *  | final               | KEEP existing (final wins)      | REPLACE (newer final wins)  |
 *
 * In words:
 *  - An incoming `final` always replaces the entry at that `start` (it
 *    supersedes an interim, and a newer final replaces an older final).
 *  - An incoming `interim` replaces a prior `interim` at the same `start`
 *    (revision), but must NOT downgrade an existing `final` — final wins.
 *
 * Everything is pure and immutable: functions return a new `CaptionState` and
 * never mutate their inputs, so property tests can assert invariants over
 * arbitrary event sequences.
 */

import type { Caption } from "../types";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/**
 * The caption-store state.
 *
 * `captions` is the canonical ordered, de-duplicated array (ascending by
 * `start`) that views read directly. `lastError`, when present, records the
 * most recent chunk error for inline display; it never affects `captions`.
 */
export interface CaptionState {
  /** Ordered (ascending `start`), de-duplicated captions. */
  captions: Caption[];
  /** The most recent chunk error, or `null` if none has occurred. */
  lastError: ChunkError | null;
}

/** A chunk-processing error surfaced to the UI without dropping captions. */
export interface ChunkError {
  /** The id of the failing chunk (from the `chunk_error` event). */
  chunkId: string;
  /** A human-readable error message. */
  message: string;
}

/** The empty initial caption state. */
export const INITIAL_CAPTION_STATE: CaptionState = {
  captions: [],
  lastError: null,
};

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Decide whether an `incoming` caption should replace an `existing` caption
 * that shares the same `start`. Returns `true` to replace, `false` to keep the
 * existing one.
 *
 * Precedence: an incoming `final` always wins; an incoming `interim` only wins
 * over an existing `interim` (it never downgrades an existing `final`).
 */
function shouldReplace(existing: Caption, incoming: Caption): boolean {
  if (incoming.status === "final") {
    // A final supersedes an interim, and a newer final replaces an older final.
    return true;
  }
  // incoming is interim: replace only if the existing entry is also interim.
  return existing.status !== "final";
}

/**
 * Insert `caption` into an already-ascending, de-duplicated array, preserving
 * ordering and uniqueness by `start` and applying the precedence rules. Returns
 * a new array; the input is never mutated.
 */
function insertCaption(sorted: readonly Caption[], caption: Caption): Caption[] {
  const result: Caption[] = [];
  let inserted = false;

  for (const existing of sorted) {
    if (inserted) {
      result.push(existing);
      continue;
    }

    if (existing.start === caption.start) {
      // Same identity: apply precedence, keep position, consume the incoming.
      result.push(shouldReplace(existing, caption) ? caption : existing);
      inserted = true;
      continue;
    }

    if (caption.start < existing.start) {
      // Found the ascending insertion point.
      result.push(caption);
      inserted = true;
      result.push(existing);
      continue;
    }

    result.push(existing);
  }

  if (!inserted) {
    // Largest `start` so far (or empty array): append at the end.
    result.push(caption);
  }

  return result;
}

// ---------------------------------------------------------------------------
// Reducer functions
// ---------------------------------------------------------------------------

/**
 * Apply a single caption event.
 *
 * Inserts or replaces the caption with the same `start`, keeping the result
 * ascending by `start`, de-duplicated, and final-protected (see module docs).
 * Returns a new state; inputs are not mutated.
 */
export function applyCaption(state: CaptionState, caption: Caption): CaptionState {
  return {
    ...state,
    captions: insertCaption(state.captions, caption),
  };
}

/**
 * Apply a chunk-error event.
 *
 * Records the latest error for inline UI display and explicitly retains all
 * already-displayed captions (Req 1.9). Returns a new state; inputs are not
 * mutated.
 */
export function applyChunkError(
  state: CaptionState,
  error: ChunkError,
): CaptionState {
  return {
    captions: state.captions,
    lastError: { chunkId: error.chunkId, message: error.message },
  };
}

/**
 * Replace the entire caption collection (used for WebSocket replay on
 * (re)connect).
 *
 * Normalizes the input by folding the same precedence/ordering/de-dup rules
 * over the provided captions, so a replay snapshot and subsequent live events
 * converge to the same canonical state regardless of input order. The existing
 * `lastError` is preserved. Returns a new state; inputs are not mutated.
 */
export function replaceCaptions(
  state: CaptionState,
  captions: readonly Caption[],
): CaptionState {
  let next: Caption[] = [];
  for (const caption of captions) {
    next = insertCaption(next, caption);
  }
  return {
    ...state,
    captions: next,
  };
}

/** Clear all captions and any recorded error. Returns a new state. */
export function clearCaptions(state: CaptionState): CaptionState {
  return { ...state, captions: [], lastError: null };
}
