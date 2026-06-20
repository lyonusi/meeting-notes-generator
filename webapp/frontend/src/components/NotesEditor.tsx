/**
 * `NotesEditor` — markdown notes editor + Save button (task 21.1).
 *
 * A controlled textarea bound to the meeting's current notes content. The
 * parent (`NotesTranscriptView`) owns the draft state and the save/regenerate
 * side effects; this component is purely presentational so it stays easy to
 * test and reuse:
 *
 * - `content` / `onChange` drive the editable markdown (Req 7.4).
 * - `onSave` persists the draft as a new version; the button is disabled while
 *   a save is in flight or when there is nothing to edit (Req 7.4, 7.6).
 * - `onRegenerate` requests freshly generated notes for review *without*
 *   persisting them (Req 7.8); on failure the parent retains the prior notes
 *   (Req 7.9).
 * - `status` renders the inline save confirmation ("Saved as version N") or an
 *   error message (Req 7.4, 7.5, 7.9).
 */

/** A small inline status banner shown under the editor. */
export interface EditorStatus {
  /** `"success"` renders the confirmation style; `"error"` the error style. */
  type: "success" | "error";
  /** The message to display (e.g. "Saved as version 3"). */
  text: string;
}

export interface NotesEditorProps {
  /** The current editable notes markdown. */
  content: string;
  /** Called with the new value on every edit. */
  onChange: (value: string) => void;
  /** Persist the current content as a new version (Req 7.4, 7.6). */
  onSave: () => void;
  /** Regenerate notes for review without persisting (Req 7.8). */
  onRegenerate: () => void;
  /** True while a save request is in flight. */
  saving: boolean;
  /** True while a regeneration request is in flight. */
  regenerating: boolean;
  /** Inline confirmation/error status, or `null` for none. */
  status: EditorStatus | null;
  /** When true, the editor and actions are disabled (e.g. no open document). */
  disabled?: boolean;
}

export default function NotesEditor({
  content,
  onChange,
  onSave,
  onRegenerate,
  saving,
  regenerating,
  status,
  disabled = false,
}: NotesEditorProps) {
  const busy = saving || regenerating;
  const canSave = !disabled && !busy;

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Notes
        </h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRegenerate}
            disabled={disabled || busy}
            className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {regenerating
              ? "Generating…"
              : content.trim().length === 0
                ? "Generate Notes"
                : "Regenerate"}
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={!canSave}
            className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-blue-600"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      <textarea
        aria-label="Notes editor"
        value={content}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled || busy}
        spellCheck={false}
        placeholder="Meeting notes will appear here. Edit and Save to create a new version."
        className="h-full min-h-[20rem] w-full flex-1 resize-none rounded-lg border border-slate-300 bg-white px-3 py-2.5 font-mono text-sm leading-relaxed text-slate-900 shadow-sm transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
      />

      {status !== null && (
        <p
          role={status.type === "error" ? "alert" : "status"}
          className={
            status.type === "error"
              ? "text-sm font-medium text-red-600"
              : "text-sm font-medium text-emerald-600"
          }
        >
          {status.text}
        </p>
      )}
    </div>
  );
}
