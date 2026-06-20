/**
 * Typed HTTP API client for the live-transcription web UI (task 15.1).
 *
 * This module is the single place the frontend talks to the FastAPI backend's
 * HTTP surface (the `useWebSocket` hook in task 17.1 owns the streaming
 * `/ws/captions` channel). It provides:
 *
 * - Typed request/response wrappers for every endpoint in the design's
 *   "Backend API Surface" table.
 * - Error-envelope handling: the backend returns errors as
 *   `{error: {code, message, resource?}}` with HTTP status codes (404
 *   not-found Req 4.6, 409 invalid transition Req 4.7, 422 unavailable device
 *   Req 4.8, 4xx invalid config Req 6.7). Non-2xx responses are parsed and
 *   thrown as a typed {@link ApiError} so callers can show messages.
 * - A distinct backend-unavailable signal (Req 9.5): when `fetch` itself
 *   rejects (backend down / unreachable / DNS / CORS), the failure is surfaced
 *   as an {@link ApiError} with `code === BACKEND_UNAVAILABLE_CODE`, so the UI
 *   (task 22) can render an "unavailable" indicator distinct from HTTP errors.
 *
 * The base URL is relative ("/api/..."): the Vite dev server proxies `/api` to
 * the backend, and in production the SPA is served from the same origin.
 */

import type {
  AppConfig,
  Device,
  MeetingSummary,
  Model,
  NotesVersion,
  SessionState,
  StopResult,
  TranscriptResult,
} from "../types";

// ---------------------------------------------------------------------------
// Error envelope + typed errors
// ---------------------------------------------------------------------------

/** The error code used to signal the backend is unreachable (Req 9.5). */
export const BACKEND_UNAVAILABLE_CODE = "backend_unavailable" as const;

/**
 * The backend error envelope body: `{error: {code, message, resource?}}`.
 * Returned on every non-2xx response from the API.
 */
export interface ErrorEnvelope {
  error: {
    /** A stable machine-readable error code (e.g. `not_found`, `invalid_transition`). */
    code: string;
    /** A human-readable message safe to surface in the UI. */
    message: string;
    /** The offending resource identifier, when applicable (e.g. a meeting id). */
    resource?: string;
  };
}

/**
 * A typed error thrown for any failed API call.
 *
 * - For HTTP errors (non-2xx), {@link status} is the HTTP status code and
 *   {@link code}/{@link message}/{@link resource} come from the parsed
 *   {@link ErrorEnvelope} (falling back to sensible defaults if the body is
 *   missing or malformed).
 * - For network failures (backend down/unreachable), {@link status} is `0` and
 *   {@link code} is {@link BACKEND_UNAVAILABLE_CODE}; check
 *   {@link isBackendUnavailable} (or the `backendUnavailable` getter) to
 *   distinguish this case from a real HTTP error.
 */
export class ApiError extends Error {
  /** HTTP status code, or `0` for a network/backend-unavailable failure. */
  readonly status: number;
  /** Machine-readable error code from the envelope, or a synthesized code. */
  readonly code: string;
  /** The offending resource identifier, when the backend supplied one. */
  readonly resource?: string;

  constructor(
    status: number,
    code: string,
    message: string,
    resource?: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.resource = resource;
    // Restore the prototype chain for instanceof checks across transpilation.
    Object.setPrototypeOf(this, ApiError.prototype);
  }

  /** True when this error represents an unreachable backend (Req 9.5). */
  get backendUnavailable(): boolean {
    return this.code === BACKEND_UNAVAILABLE_CODE;
  }

  /** Construct the backend-unavailable error for a thrown network failure. */
  static backendUnavailable(cause?: unknown): ApiError {
    const detail =
      cause instanceof Error && cause.message ? `: ${cause.message}` : "";
    return new ApiError(
      0,
      BACKEND_UNAVAILABLE_CODE,
      `The backend is unavailable${detail}`,
    );
  }
}

/** Type guard: is `err` an {@link ApiError}? */
export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError;
}

/**
 * Type guard: is `err` a backend-unavailable signal (Req 9.5)?
 *
 * Lets callers (and the store's `backendAvailable` flag) treat a down backend
 * differently from an HTTP error such as 404 or 409.
 */
export function isBackendUnavailable(err: unknown): boolean {
  return isApiError(err) && err.backendUnavailable;
}

// ---------------------------------------------------------------------------
// Request/response shapes not already covered by the shared model types
// ---------------------------------------------------------------------------

/** Body for `POST /api/devices/select`. */
export interface SelectDeviceRequest {
  device_id: number;
}

/** Body for `POST /api/recording/start` (device optional; uses applied config when omitted). */
export interface StartRecordingRequest {
  device_id?: number;
}

/**
 * Response for `GET /api/meetings/{id}` — meeting detail plus its versions.
 * The summary fields are inlined alongside the full version list (Req 7.2).
 */
export interface MeetingDetail extends MeetingSummary {
  /** All saved notes versions, ordered by creation time descending (Req 7.7). */
  versions: NotesVersion[];
}

/** Response for reading notes (`GET .../notes`) and regeneration (`POST .../notes/generate`). */
export interface NotesContent {
  meeting_id: string;
  /** The notes version this content corresponds to, or `null` for generated/unsaved notes. */
  version: number | null;
  /** The notes markdown content. */
  content: string;
}

/** Body for `PUT /api/meetings/{id}/notes`. */
export interface NotesSaveRequest {
  /** The edited notes markdown to persist as a new version (Req 7.4, 7.6). */
  content: string;
}

/** Response for `PUT /api/meetings/{id}/notes` — the newly created version. */
export interface NotesSaveResponse {
  meeting_id: string;
  /** The new (strictly greater) version number created by the save (Req 7.6). */
  version: number;
  /** The saved version's metadata. */
  version_info: NotesVersion;
}

/** Body for `POST /api/meetings/{id}/notes/generate` (regenerate without persisting, Req 7.8). */
export interface NotesGenerateRequest {
  /** Optional AI model id override; defaults to the applied config when omitted. */
  ai_model_id?: string;
}

/** Body for `PUT /api/meetings/{id}/transcript`. */
export interface TranscriptSaveRequest {
  /** The edited transcript to persist (shared AWS-Transcribe-compatible shape). */
  transcript: TranscriptResult;
}

/** Response for `PUT /api/meetings/{id}/transcript`. */
export interface TranscriptSaveResponse {
  meeting_id: string;
}

/** A partial config update body for `PUT /api/config` (validated server-side, Req 6.7). */
export type ConfigUpdateRequest = Partial<AppConfig>;

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

/** The base path for all HTTP API calls; proxied to the backend in dev. */
const API_BASE = "/api";

/** Supported HTTP methods used by this client. */
type HttpMethod = "GET" | "POST" | "PUT" | "DELETE";

/** Options for an internal {@link request} call. */
interface RequestOptions {
  /** Query parameters appended to the path (undefined/null values are skipped). */
  query?: Record<string, string | number | undefined | null>;
  /** A JSON request body; serialized and sent with a JSON content-type. */
  body?: unknown;
  /** An optional AbortSignal to cancel the request. */
  signal?: AbortSignal;
}

/** Build a path with an optional, properly-encoded query string. */
function buildUrl(
  path: string,
  query?: RequestOptions["query"],
): string {
  const url = `${API_BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) {
      params.append(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

/** Narrow an unknown parsed body to an {@link ErrorEnvelope} when it matches. */
function parseErrorEnvelope(body: unknown): ErrorEnvelope["error"] | null {
  if (
    typeof body === "object" &&
    body !== null &&
    "error" in body &&
    typeof (body as { error: unknown }).error === "object" &&
    (body as { error: unknown }).error !== null
  ) {
    const error = (body as { error: Record<string, unknown> }).error;
    const code = typeof error.code === "string" ? error.code : undefined;
    const message =
      typeof error.message === "string" ? error.message : undefined;
    const resource =
      typeof error.resource === "string" ? error.resource : undefined;
    if (code !== undefined || message !== undefined) {
      return {
        code: code ?? "error",
        message: message ?? "Request failed",
        resource,
      };
    }
  }
  return null;
}

/**
 * Perform a request and parse the JSON response, throwing {@link ApiError} on
 * any failure.
 *
 * `T` is the expected success payload type. Pass `void` for endpoints that
 * return no body (e.g. an empty 204); the function resolves to `undefined`.
 */
async function request<T>(
  method: HttpMethod,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { query, body, signal } = options;
  const url = buildUrl(path, query);

  const init: RequestInit = { method, signal };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (cause) {
    // A thrown fetch means the request never reached an HTTP response:
    // backend down, network error, DNS failure, etc. (Req 9.5).
    // Re-throw genuine aborts unchanged so callers can detect cancellation.
    if (cause instanceof DOMException && cause.name === "AbortError") {
      throw cause;
    }
    throw ApiError.backendUnavailable(cause);
  }

  // Parse the body once (some error/success bodies may be empty).
  const raw = await response.text();
  let parsed: unknown = undefined;
  if (raw.length > 0) {
    try {
      parsed = JSON.parse(raw) as unknown;
    } catch {
      parsed = raw;
    }
  }

  if (!response.ok) {
    const envelope = parseErrorEnvelope(parsed);
    if (envelope) {
      throw new ApiError(
        response.status,
        envelope.code,
        envelope.message,
        envelope.resource,
      );
    }
    // Non-2xx without a recognizable envelope: synthesize from status text.
    const message =
      typeof parsed === "string" && parsed.length > 0
        ? parsed
        : response.statusText || `HTTP ${response.status}`;
    throw new ApiError(response.status, "http_error", message);
  }

  return parsed as T;
}

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------

/** `GET /api/devices` — list available input devices (may be empty). */
export function listDevices(signal?: AbortSignal): Promise<Device[]> {
  return request<Device[]>("GET", "/devices", { signal });
}

/** `POST /api/devices/select` — persist the selected input device (Req 5.2). */
export function selectDevice(
  deviceId: number,
  signal?: AbortSignal,
): Promise<void> {
  const body: SelectDeviceRequest = { device_id: deviceId };
  return request<void>("POST", "/devices/select", { body, signal });
}

// ---------------------------------------------------------------------------
// Recording control
// ---------------------------------------------------------------------------

/**
 * `POST /api/recording/start` — start a recording.
 *
 * Throws {@link ApiError} with status 422 if the device is unavailable (Req
 * 4.8) or 409 if a recording is already active (Req 4.7).
 */
export function startRecording(
  deviceId?: number,
  signal?: AbortSignal,
): Promise<SessionState> {
  const body: StartRecordingRequest =
    deviceId === undefined ? {} : { device_id: deviceId };
  return request<SessionState>("POST", "/recording/start", { body, signal });
}

/** `POST /api/recording/pause` — pause the active recording (409 if invalid, Req 4.7). */
export function pauseRecording(signal?: AbortSignal): Promise<SessionState> {
  return request<SessionState>("POST", "/recording/pause", { signal });
}

/** `POST /api/recording/resume` — resume a paused recording (409 if invalid, Req 4.7). */
export function resumeRecording(signal?: AbortSignal): Promise<SessionState> {
  return request<SessionState>("POST", "/recording/resume", { signal });
}

/** `POST /api/recording/stop` — stop and trigger the final pass (Req 2.1, 2.2). */
export function stopRecording(signal?: AbortSignal): Promise<StopResult> {
  return request<StopResult>("POST", "/recording/stop", { signal });
}

/** `GET /api/recording/state` — current session state (drives control enablement). */
export function getRecordingState(signal?: AbortSignal): Promise<SessionState> {
  return request<SessionState>("GET", "/recording/state", { signal });
}

// ---------------------------------------------------------------------------
// Meeting history + detail
// ---------------------------------------------------------------------------

/** `GET /api/meetings` — meeting history, descending by start (Req 7.1). */
export function listMeetings(signal?: AbortSignal): Promise<MeetingSummary[]> {
  return request<MeetingSummary[]>("GET", "/meetings", { signal });
}

/**
 * `GET /api/meetings/{id}` — meeting detail plus versions (Req 7.2).
 *
 * Throws {@link ApiError} with status 404 for an unknown meeting (Req 4.6).
 */
export function getMeeting(
  meetingId: string,
  signal?: AbortSignal,
): Promise<MeetingDetail> {
  return request<MeetingDetail>(
    "GET",
    `/meetings/${encodeURIComponent(meetingId)}`,
    { signal },
  );
}

// ---------------------------------------------------------------------------
// Notes
// ---------------------------------------------------------------------------

/**
 * `GET /api/meetings/{id}/notes?version=` — read notes content (Req 7.2, 7.7).
 *
 * Omit `version` to read the latest/default version. Throws {@link ApiError}
 * 404 for an unknown meeting/version (Req 4.6).
 */
export function getNotes(
  meetingId: string,
  version?: number,
  signal?: AbortSignal,
): Promise<NotesContent> {
  return request<NotesContent>(
    "GET",
    `/meetings/${encodeURIComponent(meetingId)}/notes`,
    { query: { version }, signal },
  );
}

/**
 * `PUT /api/meetings/{id}/notes` — save edited notes as a new version (Req 7.4, 7.6).
 *
 * Throws {@link ApiError} 404 for an unknown meeting (Req 4.6).
 */
export function saveNotes(
  meetingId: string,
  content: string,
  signal?: AbortSignal,
): Promise<NotesSaveResponse> {
  const body: NotesSaveRequest = { content };
  return request<NotesSaveResponse>(
    "PUT",
    `/meetings/${encodeURIComponent(meetingId)}/notes`,
    { body, signal },
  );
}

/**
 * `POST /api/meetings/{id}/notes/generate` — regenerate notes WITHOUT persisting
 * (Req 7.8). The returned content is for review; callers must explicitly save
 * via {@link saveNotes} to create a version.
 */
export function generateNotes(
  meetingId: string,
  options: NotesGenerateRequest = {},
  signal?: AbortSignal,
): Promise<NotesContent> {
  return request<NotesContent>(
    "POST",
    `/meetings/${encodeURIComponent(meetingId)}/notes/generate`,
    { body: options, signal },
  );
}

// ---------------------------------------------------------------------------
// Transcript
// ---------------------------------------------------------------------------

/**
 * `GET /api/meetings/{id}/transcript?version=` — read the transcript (Req 7.2).
 *
 * Omit `version` to read the default transcript. Throws {@link ApiError} 404
 * for an unknown meeting/version (Req 4.6).
 */
export function getTranscript(
  meetingId: string,
  version?: number,
  signal?: AbortSignal,
): Promise<TranscriptResult> {
  return request<TranscriptResult>(
    "GET",
    `/meetings/${encodeURIComponent(meetingId)}/transcript`,
    { query: { version }, signal },
  );
}

/** `PUT /api/meetings/{id}/transcript` — save an edited transcript (Req 7.4). */
export function saveTranscript(
  meetingId: string,
  transcript: TranscriptResult,
  signal?: AbortSignal,
): Promise<TranscriptSaveResponse> {
  const body: TranscriptSaveRequest = { transcript };
  return request<TranscriptSaveResponse>(
    "PUT",
    `/meetings/${encodeURIComponent(meetingId)}/transcript`,
    { body, signal },
  );
}

// ---------------------------------------------------------------------------
// Configuration + models
// ---------------------------------------------------------------------------

/** `GET /api/config` — read the applied configuration (Req 6.2). */
export function getConfig(signal?: AbortSignal): Promise<AppConfig> {
  return request<AppConfig>("GET", "/config", { signal });
}

/**
 * `PUT /api/config` — update the configuration (validated server-side).
 *
 * Throws {@link ApiError} with a 4xx status for an invalid value (Req 6.7); the
 * applied config is left unchanged in that case.
 */
export function updateConfig(
  patch: ConfigUpdateRequest,
  signal?: AbortSignal,
): Promise<AppConfig> {
  return request<AppConfig>("PUT", "/config", { body: patch, signal });
}

/** `GET /api/models` — available AI models for notes generation (Req 6.5). */
export function listModels(signal?: AbortSignal): Promise<Model[]> {
  return request<Model[]>("GET", "/models", { signal });
}

// ---------------------------------------------------------------------------
// Aggregate client object (convenience for callers that prefer a namespace)
// ---------------------------------------------------------------------------

/**
 * A namespaced object exposing every endpoint function. Equivalent to the
 * named exports; use whichever import style is clearer at the call site.
 */
export const api = {
  listDevices,
  selectDevice,
  startRecording,
  pauseRecording,
  resumeRecording,
  stopRecording,
  getRecordingState,
  listMeetings,
  getMeeting,
  getNotes,
  saveNotes,
  generateNotes,
  getTranscript,
  saveTranscript,
  getConfig,
  updateConfig,
  listModels,
} as const;

export default api;
