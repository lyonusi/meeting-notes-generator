/**
 * `TranscriptViewer` — read-only transcript display (task 21.1).
 *
 * Shows the selected meeting's full transcript text alongside the notes editor
 * (Req 7.2). The transcript is not editable here (editing transcripts is a
 * separate concern), so this is a simple presentational panel that renders the
 * text with preserved whitespace, or an empty-state message when no transcript
 * is loaded.
 */

export interface TranscriptViewerProps {
  /** The transcript plain text, or `null` when not loaded. */
  transcript: string | null;
}

export default function TranscriptViewer({ transcript }: TranscriptViewerProps) {
  const hasText = transcript !== null && transcript.trim().length > 0;

  return (
    <div className="flex h-full flex-col gap-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Transcript
      </h2>

      {hasText ? (
        <div className="h-full min-h-[20rem] flex-1 overflow-auto rounded-lg border border-slate-300 bg-slate-50 px-3 py-2.5 shadow-sm">
          <pre className="whitespace-pre-wrap break-words font-mono text-sm leading-relaxed text-slate-800">
            {transcript}
          </pre>
        </div>
      ) : (
        <p
          role="status"
          className="flex h-full min-h-[20rem] flex-1 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2.5 text-center text-sm text-slate-500"
        >
          No transcript available for this meeting.
        </p>
      )}
    </div>
  );
}
