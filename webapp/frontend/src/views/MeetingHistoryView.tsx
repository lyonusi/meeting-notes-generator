/**
 * MeetingHistoryView (task 20.1).
 *
 * Renders the meeting history list and loads a meeting's document on selection:
 *
 * - On mount, fetches the history via `api.listMeetings()` and stores it with
 *   `setMeetings`. The backend already returns meetings ordered by start
 *   timestamp descending (Req 7.1), so the list is rendered in the order
 *   received without re-sorting.
 * - On selecting a meeting, loads its detail/versions (`getMeeting`), notes
 *   (`getNotes`), and transcript (`getTranscript`) and populates
 *   `setOpenDocument` so the `NotesTranscriptView` (task 21) can display it
 *   (Req 7.2). The transcript's text is extracted from the shared
 *   AWS-Transcribe-compatible shape (`results.transcripts[0].transcript`).
 * - On a load error (an {@link ApiError}, e.g. the content can't be retrieved),
 *   an inline error message is shown and the meeting list is kept in its
 *   current state — `setMeetings` is never cleared (Req 7.3).
 * - Shows an empty-state when there are no meetings.
 *
 * Scope is limited to the history view: it only *populates* `store.openDocument`
 * on selection; rendering the open document is task 21's responsibility.
 */

import { useCallback, useEffect, useState } from "react";
import {
  getMeeting,
  getNotes,
  getTranscript,
  isApiError,
  listMeetings,
} from "../api";
import { useAppStore } from "../store";
import type { MeetingSummary, NotesVersion, TranscriptResult } from "../types";

/** Pick the version to open: the default version if present, else the first. */
function pickDefaultVersion(versions: NotesVersion[]): NotesVersion | null {
  if (versions.length === 0) return null;
  return versions.find((v) => v.is_default) ?? versions[0];
}

/** Extract the plain transcript text from the shared transcript structure. */
function transcriptText(result: TranscriptResult): string {
  const first = result.results?.transcripts?.[0]?.transcript;
  return typeof first === "string" ? first : "";
}

/** Turn any thrown value into a human-readable message for inline display. */
function errorMessage(err: unknown): string {
  if (isApiError(err)) return err.message;
  if (err instanceof Error) return err.message;
  return "An unexpected error occurred.";
}

/** Props for {@link MeetingHistoryView}. */
export interface MeetingHistoryViewProps {
  /**
   * Layout variant. `"page"` (default) is the standalone centered page with a
   * heading. `"sidebar"` renders a tighter, full-height scrollable list with no
   * outer max-width or large heading, suitable for the Meetings master pane.
   */
  variant?: "page" | "sidebar";
}

export default function MeetingHistoryView({
  variant = "page",
}: MeetingHistoryViewProps = {}) {
  const meetings = useAppStore((s) => s.meetings);
  const setMeetings = useAppStore((s) => s.setMeetings);
  const openDocument = useAppStore((s) => s.openDocument);
  const setOpenDocument = useAppStore((s) => s.setOpenDocument);

  /** True while the initial history fetch is in flight. */
  const [loadingList, setLoadingList] = useState(true);
  /** An error from the history fetch itself, or `null`. */
  const [listError, setListError] = useState<string | null>(null);

  /** The meeting id whose document is currently being loaded, or `null`. */
  const [loadingMeetingId, setLoadingMeetingId] = useState<string | null>(null);
  /** An error from loading a selected meeting's document, or `null` (Req 7.3). */
  const [selectionError, setSelectionError] = useState<string | null>(null);

  // Load the meeting history on mount. The list is stored as-is (Req 7.1).
  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    (async () => {
      setLoadingList(true);
      setListError(null);
      try {
        const result = await listMeetings(controller.signal);
        if (active) setMeetings(result);
      } catch (err) {
        if (controller.signal.aborted) return;
        if (active) setListError(errorMessage(err));
      } finally {
        if (active) setLoadingList(false);
      }
    })();

    return () => {
      active = false;
      controller.abort();
    };
  }, [setMeetings]);

  // Load a meeting's detail + notes + transcript and open it (Req 7.2). On any
  // failure, surface an inline message and keep the list untouched (Req 7.3).
  const handleSelect = useCallback(
    async (meeting: MeetingSummary) => {
      setLoadingMeetingId(meeting.meeting_id);
      setSelectionError(null);
      try {
        // Notes may not exist yet for a freshly recorded meeting (transcript
        // only). Tolerate a 404 on notes so the meeting still opens and the user
        // can generate notes; the transcript and detail must still load.
        const [detail, transcript, notes] = await Promise.all([
          getMeeting(meeting.meeting_id),
          getTranscript(meeting.meeting_id),
          getNotes(meeting.meeting_id).catch((err) => {
            if (isApiError(err) && err.status === 404) return null;
            throw err;
          }),
        ]);
        setOpenDocument({
          meeting_id: meeting.meeting_id,
          version: pickDefaultVersion(detail.versions),
          versions: detail.versions,
          notes: notes ? notes.content : "",
          transcript: transcriptText(transcript),
        });
      } catch (err) {
        // Retain the list state; only show an inline error (Req 7.3).
        setSelectionError(errorMessage(err));
      } finally {
        setLoadingMeetingId((current) =>
          current === meeting.meeting_id ? null : current,
        );
      }
    },
    [setOpenDocument],
  );

  const isSidebar = variant === "sidebar";

  // The selection error block — shared across variants (Req 7.3).
  const selectionErrorBlock = selectionError && (
    <div
      role="alert"
      className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
    >
      <span aria-hidden className="mt-0.5 select-none">⚠</span>
      <span>{selectionError}</span>
    </div>
  );

  // The main body: loading / list-error / empty / list. Shared across variants.
  const body =
    loadingList ? (
      <p className="rounded-lg border border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
        Loading meetings…
      </p>
    ) : listError ? (
      <div
        role="alert"
        className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        {listError}
      </div>
    ) : meetings.length === 0 ? (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-12 text-center">
        <p className="text-sm font-medium text-slate-700">No meetings yet</p>
        <p className="mt-1 text-sm text-slate-500">
          Recorded meetings will appear here once you finish a recording.
        </p>
      </div>
    ) : (
      <ul
        className={[
          "divide-y divide-slate-100 overflow-hidden border border-slate-200 bg-white",
          isSidebar ? "rounded-lg" : "rounded-lg shadow-sm",
        ].join(" ")}
      >
        {meetings.map((meeting) => {
          const isSelected = openDocument?.meeting_id === meeting.meeting_id;
          const isLoading = loadingMeetingId === meeting.meeting_id;
          return (
            <li key={meeting.meeting_id}>
              <button
                type="button"
                onClick={() => handleSelect(meeting)}
                disabled={isLoading}
                aria-current={isSelected ? "true" : undefined}
                className={[
                  "flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-inset",
                  isSelected
                    ? "bg-indigo-50 hover:bg-indigo-100"
                    : "hover:bg-slate-50",
                  isLoading ? "cursor-wait opacity-70" : "",
                ].join(" ")}
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900">
                    {meeting.title}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {meeting.display_date}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  {isLoading && (
                    <span className="text-xs text-slate-400">Loading…</span>
                  )}
                  <span
                    className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600"
                    title={`Latest version v${meeting.latest_version}`}
                  >
                    v{meeting.latest_version}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    );

  // Sidebar variant: tighter, full-height, scrollable; no max-width or big
  // heading. The list area scrolls within the container.
  if (isSidebar) {
    return (
      <section className="flex h-full min-h-0 w-full flex-col">
        <div className="flex shrink-0 items-baseline justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-900">Meetings</h2>
          {meetings.length > 0 && (
            <span className="text-xs text-slate-500">
              {meetings.length} meeting{meetings.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {selectionErrorBlock}
          {body}
        </div>
      </section>
    );
  }

  // Page variant (default): standalone centered page with a heading.
  return (
    <section className="mx-auto w-full max-w-3xl">
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-xl font-semibold text-slate-900">Meeting history</h2>
        {meetings.length > 0 && (
          <span className="text-sm text-slate-500">
            {meetings.length} meeting{meetings.length === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {selectionErrorBlock}
      {body}
    </section>
  );
}
