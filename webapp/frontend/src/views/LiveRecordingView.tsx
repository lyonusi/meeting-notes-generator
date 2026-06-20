/**
 * `LiveRecordingView` — the live recording screen (task 18.1).
 *
 * Composes the three sub-components (`DeviceSelector`, `RecordingControls`,
 * `CaptionStream`) and a status header that reflects the server-owned session
 * state: recording state, elapsed duration, and final-pass progress.
 *
 * On mount it loads the available input devices (`api.listDevices` ->
 * `store.setDevices`, Req 5.1) and the initial recording state
 * (`api.getRecordingState` -> `store.setSessionState`) so controls render with
 * the correct enablement before any WebSocket status events arrive. It does
 * NOT mount `useWebSocket` — that is owned by the App shell (task 22) to avoid
 * a duplicate connection; this view only reads the resulting store state.
 */

import { useEffect, useState } from "react";
import { api, isApiError } from "../api";
import { useAppStore } from "../store";
import type { RecordingStateValue } from "../types";
import CaptionStream from "../components/CaptionStream";
import DeviceSelector from "../components/DeviceSelector";
import RecordingControls from "../components/RecordingControls";

/** Format an elapsed-seconds value as `mm:ss`. */
function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

/** Presentational metadata for each recording state. */
const STATE_META: Record<
  RecordingStateValue,
  { label: string; dot: string; text: string }
> = {
  idle: { label: "Idle", dot: "bg-slate-400", text: "text-slate-600" },
  recording: { label: "Recording", dot: "bg-red-500 animate-pulse", text: "text-red-600" },
  paused: { label: "Paused", dot: "bg-amber-500", text: "text-amber-600" },
  finalizing: { label: "Finalizing", dot: "bg-blue-500 animate-pulse", text: "text-blue-600" },
};

export default function LiveRecordingView() {
  const recordingState = useAppStore((s) => s.recordingState);
  const setDevices = useAppStore((s) => s.setDevices);
  const setSessionState = useAppStore((s) => s.setSessionState);

  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    const load = async (): Promise<void> => {
      try {
        const [devices, state] = await Promise.all([
          api.listDevices(controller.signal),
          api.getRecordingState(controller.signal),
        ]);
        setDevices(devices);
        setSessionState(state);
        setLoadError(null);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setLoadError(
          isApiError(err)
            ? err.message
            : "Could not load recording state. Is the backend running?",
        );
      }
    };

    void load();
    return () => controller.abort();
  }, [setDevices, setSessionState]);

  const meta = STATE_META[recordingState.state];

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-6 p-6">
      {/* Status header */}
      <header className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm">
        <div className="flex items-center gap-3">
          <span className={`h-3 w-3 rounded-full ${meta.dot}`} aria-hidden />
          <div>
            <p className={`text-lg font-semibold ${meta.text}`}>{meta.label}</p>
            {recordingState.meeting_id !== null && (
              <p className="font-mono text-xs text-slate-400">
                {recordingState.meeting_id}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-8">
          <div className="text-right">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              Duration
            </p>
            <p className="font-mono text-2xl font-semibold tabular-nums text-slate-800">
              {formatDuration(recordingState.duration_seconds)}
            </p>
          </div>

          {recordingState.state === "finalizing" &&
            recordingState.final_progress !== null && (
              <div className="text-right">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  Final pass
                </p>
                <p className="font-mono text-2xl font-semibold tabular-nums text-blue-600">
                  {recordingState.final_progress}%
                </p>
              </div>
            )}
        </div>
      </header>

      {/* Final-pass progress bar */}
      {recordingState.state === "finalizing" &&
        recordingState.final_progress !== null && (
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full rounded-full bg-blue-500 transition-all"
              style={{ width: `${recordingState.final_progress}%` }}
              role="progressbar"
              aria-valuenow={recordingState.final_progress}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
        )}

      {loadError !== null && (
        <p
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700"
        >
          {loadError}
        </p>
      )}

      {/* Controls + device selection */}
      <section className="grid gap-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm md:grid-cols-[1fr_auto] md:items-end">
        <DeviceSelector />
        <RecordingControls />
      </section>

      {/* Live captions */}
      <section className="flex min-h-0 flex-1 flex-col gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Live captions
        </h2>
        <div className="min-h-0 flex-1">
          <CaptionStream />
        </div>
      </section>
    </div>
  );
}
