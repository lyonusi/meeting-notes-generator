/**
 * `NotesTranscriptView` — view / edit / save / version meeting notes and
 * transcript (task 21.1).
 *
 * Driven entirely by `store.openDocument`, which the Meeting History view
 * (task 20) sets when the user selects a meeting. It composes:
 *
 * - {@link NotesEditor} — edit the current notes draft and Save (Req 7.4).
 * - {@link TranscriptViewer} — read-only transcript display (Req 7.2).
 * - {@link VersionSelector} — pick a saved version, listed descending (Req 7.7).
 *
 * Behaviour mapped to the acceptance criteria:
 *
 * - Display the selected meeting's notes + transcript from `openDocument`
 *   (Req 7.2). When no document is open, an empty placeholder is shown.
 * - Save: `api.saveNotes(meetingId, content)` creates a new version
 *   server-side (Req 7.4, 7.6). On success we show "Saved as version N" and
 *   refresh the versions via `api.getMeeting`. On failure (`ApiError`) we show
 *   an error and keep the editor content untouched (Req 7.5).
 * - Version select: load that version's notes via `api.getNotes(id, version)`
 *   into the editor (Req 7.7).
 * - Regenerate: `api.generateNotes(meetingId)` returns notes for review
 *   WITHOUT persisting; we load them into the editor (Req 7.8). On failure we
 *   show an error and retain the previously displayed notes (Req 7.9).
 */

import { useState } from "react";
import NotesEditor, { type EditorStatus } from "../components/NotesEditor";
import TranscriptViewer from "../components/TranscriptViewer";
import VersionSelector from "../components/VersionSelector";
import { api, isApiError } from "../api";
import { useAppStore } from "../store";
import type { NotesVersion } from "../types";

/** Find a version record by its number within a list. */
function findVersion(
  versions: NotesVersion[],
  versionNum: number,
): NotesVersion | null {
  return versions.find((v) => v.version_num === versionNum) ?? null;
}

export default function NotesTranscriptView() {
  const openDocument = useAppStore((s) => s.openDocument);
  const setOpenDocument = useAppStore((s) => s.setOpenDocument);

  // The editable notes draft. Initialised from the open document and kept in
  // sync when the open document's notes change (e.g. a different meeting is
  // selected, a version is loaded, or notes are regenerated).
  const [draft, setDraft] = useState<string>(openDocument?.notes ?? "");
  const [loadedNotesKey, setLoadedNotesKey] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [loadingVersion, setLoadingVersion] = useState(false);
  const [status, setStatus] = useState<EditorStatus | null>(null);

  // Resync the draft when the underlying open-document notes change. We key off
  // meeting id + selected version + notes content so external loads (history
  // selection, version switch, regeneration) flow into the editor, while local
  // typing does not get clobbered.
  const docKey = openDocument
    ? `${openDocument.meeting_id}::${openDocument.version?.version_num ?? "latest"}::${openDocument.notes ?? ""}`
    : null;
  if (docKey !== loadedNotesKey) {
    setLoadedNotesKey(docKey);
    setDraft(openDocument?.notes ?? "");
  }

  if (openDocument === null) {
    return (
      <div className="flex h-full min-h-[24rem] items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 p-8">
        <div className="text-center">
          <h1 className="text-lg font-semibold text-slate-700">
            No meeting selected
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Choose a meeting from the history to view and edit its notes and
            transcript.
          </p>
        </div>
      </div>
    );
  }

  const meetingId = openDocument.meeting_id;

  /** Save the current draft as a new version (Req 7.4, 7.5, 7.6). */
  const handleSave = async (): Promise<void> => {
    setStatus(null);
    setSaving(true);
    try {
      const result = await api.saveNotes(meetingId, draft);
      // Refresh versions so the new one is selectable (Req 7.6, 7.7).
      let versions = openDocument.versions;
      let selected: NotesVersion | null = result.version_info;
      try {
        const detail = await api.getMeeting(meetingId);
        versions = detail.versions;
        selected =
          findVersion(detail.versions, result.version) ?? result.version_info;
      } catch {
        // If the refresh fails, fall back to appending the new version so the
        // UI still reflects the successful save.
        versions = [result.version_info, ...openDocument.versions];
      }
      setOpenDocument({
        ...openDocument,
        versions,
        version: selected,
        notes: draft,
      });
      setStatus({
        type: "success",
        text: `Saved as version ${result.version}`,
      });
    } catch (err) {
      // Persistence failed: keep the editor content unchanged (Req 7.5).
      setStatus({
        type: "error",
        text: isApiError(err)
          ? `Save failed: ${err.message}`
          : "Save failed. Your changes were not saved.",
      });
    } finally {
      setSaving(false);
    }
  };

  /** Load a previously saved version's notes into the editor (Req 7.7). */
  const handleSelectVersion = async (versionNum: number): Promise<void> => {
    if (openDocument.version?.version_num === versionNum) return;
    setStatus(null);
    setLoadingVersion(true);
    try {
      const notes = await api.getNotes(meetingId, versionNum);
      const selected = findVersion(openDocument.versions, versionNum);
      setOpenDocument({
        ...openDocument,
        version: selected,
        notes: notes.content,
      });
    } catch (err) {
      setStatus({
        type: "error",
        text: isApiError(err)
          ? `Could not load version ${versionNum}: ${err.message}`
          : `Could not load version ${versionNum}.`,
      });
    } finally {
      setLoadingVersion(false);
    }
  };

  /**
   * Regenerate notes for review WITHOUT persisting (Req 7.8). On failure retain
   * the previously displayed notes (Req 7.9).
   */
  const handleRegenerate = async (): Promise<void> => {
    setStatus(null);
    setRegenerating(true);
    try {
      const generated = await api.generateNotes(meetingId);
      // Show generated notes for review; do not persist or change versions.
      setOpenDocument({
        ...openDocument,
        notes: generated.content,
      });
      setStatus({
        type: "success",
        text: "Regenerated notes for review. Save to keep them as a new version.",
      });
    } catch (err) {
      // Regeneration failed: retain the most recently displayed notes (Req 7.9).
      setStatus({
        type: "error",
        text: isApiError(err)
          ? `Regeneration failed: ${err.message}`
          : "Regeneration failed. The previous notes are unchanged.",
      });
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">
            Notes &amp; Transcript
          </h1>
          <p className="text-sm text-slate-500">Meeting {meetingId}</p>
        </div>
        <div className="w-full max-w-xs">
          <VersionSelector
            versions={openDocument.versions}
            selectedVersion={openDocument.version?.version_num ?? null}
            onSelect={handleSelectVersion}
            disabled={loadingVersion || saving || regenerating}
          />
        </div>
      </div>

      <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="flex flex-col rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <NotesEditor
            content={draft}
            onChange={setDraft}
            onSave={handleSave}
            onRegenerate={handleRegenerate}
            saving={saving}
            regenerating={regenerating}
            status={status}
            disabled={loadingVersion}
          />
        </section>

        <section className="flex flex-col rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <TranscriptViewer transcript={openDocument.transcript} />
        </section>
      </div>
    </div>
  );
}
