/**
 * `useWebSocket` — live caption / status WebSocket client (task 17.1).
 *
 * Connects to the backend `/ws/captions` channel and drives the Zustand store
 * (`store.ts`) from the server event stream. The server sends envelopes of the
 * form `{type, seq, payload}` (design "WebSocket Channel" table). On every
 * (re)connect the backend first replays the buffered caption snapshot in
 * ascending `start` order and then resumes live events (Req 1.6); because the
 * caption reducer is idempotent and de-duplicates by `start`, simply applying
 * each `caption` envelope in arrival order through `store.applyCaption`
 * converges to the correct displayed state (Req 1.3, 1.6).
 *
 * Behavior summary:
 *  - `caption`         -> `store.applyCaption(...)` (ordering/de-dup/latest-wins)
 *  - `status`          -> merge `{state, duration}` into `recordingState`
 *  - `final_progress`  -> update `recordingState.final_progress`
 *  - `chunk_error`     -> `store.applyChunkError(...)` (keeps captions, Req 1.9)
 *  - `final_result` / `missing_recording` / `silent_warning` / `device_error`
 *                      -> surfaced as a transient `lastNotification` (the hook
 *                         return value) so views can render them
 *  - auto-reconnects with capped exponential backoff; toggles
 *    `store.setBackendAvailable` on open/close (ties into Req 9.5 / task 22)
 *  - cleans up the socket and timers on unmount / when disabled
 */

import { useEffect, useRef, useState } from "react";
import type {
  Caption,
  CaptionStatus,
  RecordingStateValue,
} from "../types";
import { useAppStore } from "../store/store";

// ---------------------------------------------------------------------------
// Server event envelope union
// ---------------------------------------------------------------------------

/** Payload of a `caption` event — mirrors the {@link Caption} model. */
export interface CaptionPayload {
  text: string;
  start: number;
  end: number;
  status: CaptionStatus;
}

/** Payload of a `status` event (Req 4.4). */
export interface StatusPayload {
  state: RecordingStateValue;
  duration: number;
}

/** Payload of a `final_progress` event (0..100) (Req 2.6). */
export interface FinalProgressPayload {
  percent: number;
}

/** Payload of a `chunk_error` event (Req 1.8, 1.9). */
export interface ChunkErrorPayload {
  chunk_id: string | number;
  message: string;
}

/** The outcome of the final transcription pass (Req 2.3, 2.5, 2.8). */
export type FinalResultOutcome = "authoritative" | "fallback" | "failed";

/** Payload of a `final_result` event. */
export interface FinalResultPayload {
  outcome: FinalResultOutcome;
}

/** Payload of a `missing_recording` event (Req 2.2). */
export interface MissingRecordingPayload {
  meeting_id: string;
}

/** Payload of a `silent_warning` event (Req 5.8). */
export interface SilentWarningPayload {
  meeting_id: string;
  peak_amplitude: number;
}

/** Payload of a `device_error` event (Req 5.6). */
export interface DeviceErrorPayload {
  message: string;
}

/** A single server -> client event envelope: `{type, seq, payload}`. */
export type WsEnvelope =
  | { type: "caption"; seq: number | null; payload: CaptionPayload }
  | { type: "status"; seq: number | null; payload: StatusPayload }
  | { type: "final_progress"; seq: number | null; payload: FinalProgressPayload }
  | { type: "chunk_error"; seq: number | null; payload: ChunkErrorPayload }
  | { type: "final_result"; seq: number | null; payload: FinalResultPayload }
  | {
      type: "missing_recording";
      seq: number | null;
      payload: MissingRecordingPayload;
    }
  | { type: "silent_warning"; seq: number | null; payload: SilentWarningPayload }
  | { type: "device_error"; seq: number | null; payload: DeviceErrorPayload };

/** The discriminant `type` values the hook understands. */
export type WsEventType = WsEnvelope["type"];

// ---------------------------------------------------------------------------
// Notifications surfaced from the hook
// ---------------------------------------------------------------------------

/**
 * A transient, non-caption notification surfaced to the caller. These events
 * are one-shot signals (not part of the converged caption/session state), so
 * the hook exposes only the most recent one via its return value; the live view
 * (task 18+) decides how to render it.
 */
export type WsNotification =
  | { type: "final_result"; outcome: FinalResultOutcome }
  | { type: "missing_recording"; meetingId: string }
  | { type: "silent_warning"; meetingId: string; peakAmplitude: number }
  | { type: "device_error"; message: string };

// ---------------------------------------------------------------------------
// Hook options + return
// ---------------------------------------------------------------------------

/** Options for {@link useWebSocket}. */
export interface UseWebSocketOptions {
  /**
   * When `false`, the hook keeps the socket closed (and closes an open one).
   * Defaults to `true` so the channel is live for the whole app session and the
   * backend can replay/stream whenever a recording is active.
   */
  enabled?: boolean;
}

/** The value returned by {@link useWebSocket}. */
export interface UseWebSocketResult {
  /** Whether the WebSocket is currently open. */
  connected: boolean;
  /**
   * The most recent transient notification (final result, missing recording,
   * silent warning, or device error), or `null` if none has arrived. Replaced
   * as new notifications arrive.
   */
  lastNotification: WsNotification | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Initial reconnect delay (ms). Doubles each attempt up to the cap. */
const RECONNECT_BASE_DELAY_MS = 500;
/** Maximum reconnect backoff delay (ms). */
const RECONNECT_MAX_DELAY_MS = 10_000;

// ---------------------------------------------------------------------------
// URL + parsing helpers
// ---------------------------------------------------------------------------

/**
 * Build the absolute `/ws/captions` URL relative to the current origin so the
 * Vite dev proxy (`vite.config.ts` forwards `/ws` to the backend) and the
 * production same-origin deployment both work. Chooses `wss:` on HTTPS pages.
 */
function buildCaptionsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/captions`;
}

/** Narrow an unknown value to a finite number, else `null`. */
function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Coerce an unknown caption `status` to a valid {@link CaptionStatus}. */
function asCaptionStatus(value: unknown): CaptionStatus {
  return value === "final" ? "final" : "interim";
}

/**
 * Parse a raw WebSocket message into a typed {@link WsEnvelope}, or return
 * `null` for malformed / unknown messages (which are ignored rather than
 * crashing the stream).
 */
function parseEnvelope(data: unknown): WsEnvelope | null {
  if (typeof data !== "string") return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }

  if (typeof parsed !== "object" || parsed === null) return null;
  const obj = parsed as Record<string, unknown>;
  const type = obj.type;
  const payload = obj.payload;
  if (typeof type !== "string") return null;
  if (typeof payload !== "object" || payload === null) return null;

  const seqRaw = obj.seq;
  const seq = typeof seqRaw === "number" ? seqRaw : null;
  const p = payload as Record<string, unknown>;

  switch (type) {
    case "caption": {
      const start = asFiniteNumber(p.start);
      const end = asFiniteNumber(p.end);
      if (start === null || end === null) return null;
      const text = typeof p.text === "string" ? p.text : "";
      return {
        type: "caption",
        seq,
        payload: { text, start, end, status: asCaptionStatus(p.status) },
      };
    }
    case "status": {
      const state = p.state;
      if (
        state !== "idle" &&
        state !== "recording" &&
        state !== "paused" &&
        state !== "finalizing"
      ) {
        return null;
      }
      const duration = asFiniteNumber(p.duration) ?? 0;
      return { type: "status", seq, payload: { state, duration } };
    }
    case "final_progress": {
      const percent = asFiniteNumber(p.percent);
      if (percent === null) return null;
      return { type: "final_progress", seq, payload: { percent } };
    }
    case "chunk_error": {
      const chunkId =
        typeof p.chunk_id === "string" || typeof p.chunk_id === "number"
          ? p.chunk_id
          : "";
      const message = typeof p.message === "string" ? p.message : "";
      return {
        type: "chunk_error",
        seq,
        payload: { chunk_id: chunkId, message },
      };
    }
    case "final_result": {
      const outcome = p.outcome;
      if (
        outcome !== "authoritative" &&
        outcome !== "fallback" &&
        outcome !== "failed"
      ) {
        return null;
      }
      return { type: "final_result", seq, payload: { outcome } };
    }
    case "missing_recording": {
      const meetingId = typeof p.meeting_id === "string" ? p.meeting_id : "";
      return {
        type: "missing_recording",
        seq,
        payload: { meeting_id: meetingId },
      };
    }
    case "silent_warning": {
      const meetingId = typeof p.meeting_id === "string" ? p.meeting_id : "";
      const peak = asFiniteNumber(p.peak_amplitude) ?? 0;
      return {
        type: "silent_warning",
        seq,
        payload: { meeting_id: meetingId, peak_amplitude: peak },
      };
    }
    case "device_error": {
      const message = typeof p.message === "string" ? p.message : "";
      return { type: "device_error", seq, payload: { message } };
    }
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Open and manage the `/ws/captions` WebSocket connection, dispatching server
 * events into the global store. See the module docstring for the full
 * dispatch/reconnect contract.
 *
 * @param options - {@link UseWebSocketOptions}; set `enabled: false` to keep the
 *   socket closed.
 * @returns {@link UseWebSocketResult} with the current connection flag and the
 *   most recent transient notification.
 */
export function useWebSocket(
  options: UseWebSocketOptions = {},
): UseWebSocketResult {
  const { enabled = true } = options;

  const [connected, setConnected] = useState(false);
  const [lastNotification, setLastNotification] =
    useState<WsNotification | null>(null);

  // Mutable refs for the live socket, the pending reconnect timer, the current
  // backoff delay, and a teardown guard so async callbacks don't act after the
  // effect has been cleaned up.
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef = useRef(RECONNECT_BASE_DELAY_MS);
  const disposedRef = useRef(false);

  useEffect(() => {
    if (!enabled) return;

    disposedRef.current = false;

    // Store actions are read fresh from `getState()` inside the message
    // handler so the effect does not need to re-subscribe to the store.
    const store = useAppStore;

    const clearReconnectTimer = (): void => {
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const scheduleReconnect = (): void => {
      if (disposedRef.current) return;
      clearReconnectTimer();
      const delay = reconnectDelayRef.current;
      reconnectDelayRef.current = Math.min(delay * 2, RECONNECT_MAX_DELAY_MS);
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    const dispatch = (envelope: WsEnvelope): void => {
      const s = store.getState();
      switch (envelope.type) {
        case "caption": {
          const caption: Caption = {
            text: envelope.payload.text,
            start: envelope.payload.start,
            end: envelope.payload.end,
            status: envelope.payload.status,
          };
          s.applyCaption(caption);
          break;
        }
        case "status": {
          // Merge state + duration onto the existing session state, preserving
          // other fields (meeting_id, device_id, started_at, final_progress).
          s.setSessionState({
            ...s.recordingState,
            state: envelope.payload.state,
            duration_seconds: envelope.payload.duration,
          });
          break;
        }
        case "final_progress": {
          s.setSessionState({
            ...s.recordingState,
            final_progress: envelope.payload.percent,
          });
          break;
        }
        case "chunk_error": {
          // Retains displayed captions; records inline error (Req 1.9).
          s.applyChunkError(
            String(envelope.payload.chunk_id),
            envelope.payload.message,
          );
          break;
        }
        case "final_result": {
          setLastNotification({
            type: "final_result",
            outcome: envelope.payload.outcome,
          });
          break;
        }
        case "missing_recording": {
          setLastNotification({
            type: "missing_recording",
            meetingId: envelope.payload.meeting_id,
          });
          break;
        }
        case "silent_warning": {
          setLastNotification({
            type: "silent_warning",
            meetingId: envelope.payload.meeting_id,
            peakAmplitude: envelope.payload.peak_amplitude,
          });
          break;
        }
        case "device_error": {
          setLastNotification({
            type: "device_error",
            message: envelope.payload.message,
          });
          break;
        }
      }
    };

    function connect(): void {
      if (disposedRef.current) return;
      reconnectTimerRef.current = null;

      let socket: WebSocket;
      try {
        socket = new WebSocket(buildCaptionsUrl());
      } catch {
        // Construction can throw on a malformed URL / environment; treat it as
        // a disconnect and back off.
        store.getState().setBackendAvailable(false);
        setConnected(false);
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        if (disposedRef.current) return;
        // Reset backoff on a successful connection (Req 9.5).
        reconnectDelayRef.current = RECONNECT_BASE_DELAY_MS;
        setConnected(true);
        store.getState().setBackendAvailable(true);
      };

      socket.onmessage = (event: MessageEvent) => {
        if (disposedRef.current) return;
        const envelope = parseEnvelope(event.data);
        if (envelope !== null) dispatch(envelope);
      };

      socket.onerror = () => {
        // `onerror` is followed by `onclose`; let `onclose` drive reconnect so
        // we don't schedule twice. Surface unavailability immediately.
        if (disposedRef.current) return;
        store.getState().setBackendAvailable(false);
      };

      socket.onclose = () => {
        if (disposedRef.current) return;
        socketRef.current = null;
        setConnected(false);
        store.getState().setBackendAvailable(false);
        scheduleReconnect();
      };
    }

    connect();

    // Cleanup: stop reconnecting and close the socket without triggering the
    // reconnect path from `onclose`.
    return () => {
      disposedRef.current = true;
      clearReconnectTimer();
      reconnectDelayRef.current = RECONNECT_BASE_DELAY_MS;
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        socket.close();
      }
      setConnected(false);
    };
  }, [enabled]);

  return { connected, lastNotification };
}

export default useWebSocket;
