/**
 * `App` — the application shell.
 *
 * Top-level layout tying the two pages together and owning the single, app-wide
 * WebSocket connection. Responsibilities:
 *
 * - **Navigation / layout.** A titled header plus a top nav with two sections —
 *   Record and Meetings. View switching is done with local React state
 *   (`useState`) rather than a router: `react-router` is not a dependency and
 *   we deliberately avoid adding one. The active page is highlighted and its
 *   component is rendered in the content area.
 *
 *   - **Record** ({@link RecordPage}) hosts the live recording view with
 *     Configuration available via a slide-over drawer.
 *   - **Meetings** ({@link MeetingsPage}) is a master–detail layout: the
 *     meeting list on the left, the selected meeting's notes/transcript on the
 *     right (filled in place, no nav switch).
 *
 * - **Single WebSocket mount (Req 1.3).** `useWebSocket` is mounted exactly
 *   once here, at the app level. The views were intentionally written to NOT
 *   mount it so there is only ever one `/ws/captions` connection; they read the
 *   resulting store state instead. The hook's `lastNotification` is surfaced as
 *   a transient, dismissible banner (final result / silent warning /
 *   device error / missing recording).
 *
 * - **Backend-unavailable indicator (Req 9.5).** Reads `store.backendAvailable`
 *   (toggled by the api client on network failures and by the ws hook on
 *   open/close) and shows a clear, persistent banner while the backend is down.
 */

import { useState } from "react";
import { useAppStore } from "./store";
import { useWebSocket, type WsNotification } from "./hooks/useWebSocket";
import RecordPage from "./pages/RecordPage";
import MeetingsPage from "./pages/MeetingsPage";

/** The two top-level pages the shell can render. */
type PageId = "record" | "meetings";

/** Nav metadata for each page, rendered in order. */
const NAV_ITEMS: ReadonlyArray<{ id: PageId; label: string }> = [
  { id: "record", label: "Record" },
  { id: "meetings", label: "Meetings" },
];

/** Render the component for the active page. */
function ActivePage({ page }: { page: PageId }) {
  switch (page) {
    case "record":
      return <RecordPage />;
    case "meetings":
      return <MeetingsPage />;
  }
}

/** Map a transient WS notification to a human-readable banner message + tone. */
function notificationView(
  n: WsNotification,
): { tone: "info" | "warning" | "error"; text: string } {
  switch (n.type) {
    case "final_result":
      switch (n.outcome) {
        case "authoritative":
          return {
            tone: "info",
            text: "Final transcript ready — notes can be generated from the authoritative transcript.",
          };
        case "fallback":
          return {
            tone: "warning",
            text: "Final pass unavailable — using the live captions as the transcript.",
          };
        case "failed":
          return {
            tone: "error",
            text: "Final transcription pass failed. Your recording and live captions were kept.",
          };
      }
    // eslint-disable-next-line no-fallthrough
    case "missing_recording":
      return {
        tone: "warning",
        text: `No recording was captured for meeting ${n.meetingId}.`,
      };
    case "silent_warning":
      return {
        tone: "warning",
        text: `Recording ${n.meetingId} appears silent (peak amplitude ${n.peakAmplitude}). Check your input device.`,
      };
    case "device_error":
      return { tone: "error", text: n.message };
  }
}

const TONE_STYLES: Record<"info" | "warning" | "error", string> = {
  info: "border-blue-200 bg-blue-50 text-blue-800",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  error: "border-red-200 bg-red-50 text-red-800",
};

export default function App() {
  const [page, setPage] = useState<PageId>("record");

  // Mount the live caption / status WebSocket exactly once for the whole app.
  const { connected, lastNotification } = useWebSocket();

  const backendAvailable = useAppStore((s) => s.backendAvailable);

  // The transient notification banner is dismissible; track which notification
  // has been dismissed so a new one re-shows.
  const [dismissedNotification, setDismissedNotification] =
    useState<WsNotification | null>(null);
  const showNotification =
    lastNotification !== null && lastNotification !== dismissedNotification;

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      {/* Header */}
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-4">
          <div className="flex items-center gap-3">
            <span
              className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 text-sm font-bold text-white"
              aria-hidden
            >
              MN
            </span>
            <div>
              <h1 className="text-lg font-semibold leading-tight text-slate-900">
                Meeting Notes
              </h1>
              <p className="text-xs text-slate-500">Live Transcription</p>
            </div>
          </div>

          {/* Connection badge */}
          <span
            className={[
              "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium",
              connected
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-slate-200 bg-slate-50 text-slate-500",
            ].join(" ")}
            title={connected ? "Live connection open" : "Live connection closed"}
          >
            <span
              className={[
                "h-2 w-2 rounded-full",
                connected ? "bg-emerald-500" : "bg-slate-400",
              ].join(" ")}
              aria-hidden
            />
            {connected ? "Live" : "Offline"}
          </span>
        </div>

        {/* Navigation */}
        <nav className="mx-auto max-w-6xl px-4">
          <ul className="flex flex-wrap gap-1">
            {NAV_ITEMS.map((item) => {
              const active = page === item.id;
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => setPage(item.id)}
                    aria-current={active ? "page" : undefined}
                    className={[
                      "relative px-4 py-3 text-sm font-medium transition-colors",
                      "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-inset",
                      active
                        ? "text-indigo-700"
                        : "text-slate-500 hover:text-slate-800",
                    ].join(" ")}
                  >
                    {item.label}
                    <span
                      className={[
                        "absolute inset-x-2 -bottom-px h-0.5 rounded-full transition-colors",
                        active ? "bg-indigo-600" : "bg-transparent",
                      ].join(" ")}
                      aria-hidden
                    />
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>

      {/* Backend-unavailable banner (Req 9.5). */}
      {!backendAvailable && (
        <div
          role="status"
          aria-live="polite"
          className="border-b border-red-200 bg-red-600 text-white"
        >
          <div className="mx-auto flex max-w-6xl items-center gap-2 px-6 py-2 text-sm font-medium">
            <span
              className="h-2 w-2 animate-pulse rounded-full bg-white"
              aria-hidden
            />
            Backend unavailable — reconnecting…
          </div>
        </div>
      )}

      {/* Transient WS notification banner. */}
      {showNotification && lastNotification && (
        <NotificationBanner
          notification={lastNotification}
          onDismiss={() => setDismissedNotification(lastNotification)}
        />
      )}

      {/* Content area */}
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <ActivePage page={page} />
      </main>
    </div>
  );
}

/** A dismissible banner rendering a single transient WS notification. */
function NotificationBanner({
  notification,
  onDismiss,
}: {
  notification: WsNotification;
  onDismiss: () => void;
}) {
  const { tone, text } = notificationView(notification);
  return (
    <div
      role="status"
      aria-live="polite"
      className={`border-b ${TONE_STYLES[tone]}`}
    >
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-2.5 text-sm">
        <span>{text}</span>
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 rounded-md px-2 py-0.5 text-xs font-medium underline-offset-2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
          aria-label="Dismiss notification"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
