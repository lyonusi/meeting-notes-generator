/**
 * `MeetingsPage` — Page 2 of the consolidated two-page shell.
 *
 * A master–detail layout: the meeting list (the `sidebar` variant of
 * {@link MeetingHistoryView}) sits in a narrow left column, and the selected
 * meeting's {@link NotesTranscriptView} fills the remaining width on the right.
 *
 * Selecting a meeting sets `store.openDocument` (handled inside the history
 * view); the right pane reads that store value and fills in place — no nav
 * switch. When nothing is selected, the right pane shows the
 * NotesTranscriptView empty state (it handles `openDocument === null`).
 *
 * Responsive: the two columns stack vertically on small screens and sit
 * side-by-side from the `lg` breakpoint up.
 */

import MeetingHistoryView from "../views/MeetingHistoryView";
import NotesTranscriptView from "../views/NotesTranscriptView";

export default function MeetingsPage() {
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 lg:flex-row">
      {/* Master: meeting list (narrow, scrollable). */}
      <aside className="w-full shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm lg:h-full lg:w-80">
        <MeetingHistoryView variant="sidebar" />
      </aside>

      {/* Detail: selected meeting's notes + transcript (fills remaining width). */}
      <div className="min-h-0 min-w-0 flex-1">
        <NotesTranscriptView />
      </div>
    </div>
  );
}
