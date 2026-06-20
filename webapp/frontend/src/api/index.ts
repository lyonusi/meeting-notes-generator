/**
 * Public entry point for the typed HTTP API client (task 15.1).
 *
 * Re-exports the endpoint functions, the `api` namespace object, the typed
 * `ApiError` (including the backend-unavailable signal, Req 9.5), and the
 * request/response interfaces so views and the store can import from
 * `../api` without reaching into `./client`.
 */

export * from "./client";
export { api as default } from "./client";
