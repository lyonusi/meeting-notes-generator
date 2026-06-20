/**
 * `VersionSelector` — notes-version dropdown (task 21.1).
 *
 * Lists every saved `NotesVersion` for the open meeting ordered by creation
 * time descending (Req 7.7), so the most recent version appears first.
 * Selecting a version asks the parent to load that version's notes into the
 * editor (`api.getNotes(meetingId, version)`).
 *
 * Ordering is enforced here defensively (the store is expected to already hold
 * descending versions, but the dropdown owns the display contract for Req 7.7).
 */

import { useMemo } from "react";
import type { NotesVersion } from "../types";

export interface VersionSelectorProps {
  /** All saved versions for the meeting (any order; sorted here descending). */
  versions: NotesVersion[];
  /** The currently selected version number, or `null` for the latest/default. */
  selectedVersion: number | null;
  /** Called with the chosen version number when the selection changes. */
  onSelect: (versionNum: number) => void;
  /** When true, the control is disabled (e.g. while loading). */
  disabled?: boolean;
}

/** Sort a copy of `versions` by creation time descending (Req 7.7). */
function sortByCreationDesc(versions: NotesVersion[]): NotesVersion[] {
  return [...versions].sort((a, b) => {
    const ta = Date.parse(a.creation_time);
    const tb = Date.parse(b.creation_time);
    // Fall back to version number when timestamps are equal/unparseable.
    if (Number.isNaN(ta) || Number.isNaN(tb) || ta === tb) {
      return b.version_num - a.version_num;
    }
    return tb - ta;
  });
}

export default function VersionSelector({
  versions,
  selectedVersion,
  onSelect,
  disabled = false,
}: VersionSelectorProps) {
  const ordered = useMemo(() => sortByCreationDesc(versions), [versions]);

  const handleChange = (
    event: React.ChangeEvent<HTMLSelectElement>,
  ): void => {
    const raw = event.target.value;
    if (raw === "") return;
    const versionNum = Number(raw);
    if (!Number.isFinite(versionNum)) return;
    onSelect(versionNum);
  };

  return (
    <div className="flex flex-col gap-2">
      <label
        htmlFor="version-selector"
        className="text-xs font-semibold uppercase tracking-wide text-slate-500"
      >
        Version
      </label>

      {ordered.length === 0 ? (
        <p
          role="status"
          className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2.5 text-sm text-slate-500"
        >
          No saved versions yet.
        </p>
      ) : (
        <select
          id="version-selector"
          value={selectedVersion ?? ordered[0].version_num}
          onChange={handleChange}
          disabled={disabled}
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
        >
          {ordered.map((version) => (
            <option key={version.version_num} value={version.version_num}>
              {version.name}
              {version.is_default ? " (default)" : ""}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
