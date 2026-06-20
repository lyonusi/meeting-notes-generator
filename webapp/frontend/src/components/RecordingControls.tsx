/**
 * `RecordingControls` — Start / Pause / Resume / Stop buttons (task 18.1).
 *
 * Button enablement is a strict function of `store.recordingState.state`
 * (Property 15, Req 5.3/5.4):
 *
 *  | state       | Start | Pause | Resume | Stop |
 *  |-------------|-------|-------|--------|------|
 *  | idle        |   ✓   |       |        |      |
 *  | recording   |       |   ✓   |        |  ✓   |
 *  | paused      |       |       |   ✓    |  ✓   |
 *  | finalizing  |       |       |        |      |
 *
 * Each button calls the matching `api.*Recording()` endpoint and folds the
 * returned `SessionState` back into the store. Stop returns a `StopResult`
 * (not a session state), so after a successful stop we re-fetch the session
 * state so controls reflect the new (finalizing/idle) value. `ApiError`s
 * (e.g. `device_error` 422, `invalid_transition` 409) are surfaced inline
 * without changing local state.
 */

import { useState } from "react";
import { api, isApiError } from "../api";
import { useAppStore } from "../store";

/** A small presentational button used by the controls row. */
function ControlButton({
  label,
  onClick,
  disabled,
  variant,
  pending,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  variant: "record" | "primary" | "neutral" | "danger";
  pending: boolean;
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold shadow-sm transition focus:outline-none focus:ring-2 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-40";
  const variants: Record<typeof variant, string> = {
    record:
      "bg-red-600 text-white hover:bg-red-500 focus:ring-red-500/40 disabled:hover:bg-red-600",
    primary:
      "bg-blue-600 text-white hover:bg-blue-500 focus:ring-blue-500/40 disabled:hover:bg-blue-600",
    neutral:
      "bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 focus:ring-slate-400/40",
    danger:
      "bg-slate-800 text-white hover:bg-slate-700 focus:ring-slate-500/40 disabled:hover:bg-slate-800",
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || pending}
      className={`${base} ${variants[variant]}`}
    >
      {label}
    </button>
  );
}

export default function RecordingControls() {
  const recordingState = useAppStore((s) => s.recordingState);
  const setSessionState = useAppStore((s) => s.setSessionState);

  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const state = recordingState.state;

  // Enablement is derived strictly from the recording state (Req 5.3, 5.4).
  const canStart = state === "idle";
  const canPause = state === "recording";
  const canResume = state === "paused";
  const canStop = state === "recording" || state === "paused";

  const run = async (
    action: () => Promise<void>,
  ): Promise<void> => {
    setError(null);
    setPending(true);
    try {
      await action();
    } catch (err) {
      setError(isApiError(err) ? err.message : "The action could not be completed.");
    } finally {
      setPending(false);
    }
  };

  const handleStart = () =>
    run(async () => {
      const next = await api.startRecording(recordingState.device_id ?? undefined);
      setSessionState(next);
    });

  const handlePause = () =>
    run(async () => {
      const next = await api.pauseRecording();
      setSessionState(next);
    });

  const handleResume = () =>
    run(async () => {
      const next = await api.resumeRecording();
      setSessionState(next);
    });

  const handleStop = () =>
    run(async () => {
      await api.stopRecording();
      // Stop returns a StopResult; refresh the authoritative session state so
      // controls reflect the new (finalizing/idle) value.
      const next = await api.getRecordingState();
      setSessionState(next);
    });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <ControlButton
          label="● Start"
          variant="record"
          onClick={handleStart}
          disabled={!canStart}
          pending={pending}
        />
        <ControlButton
          label="Pause"
          variant="neutral"
          onClick={handlePause}
          disabled={!canPause}
          pending={pending}
        />
        <ControlButton
          label="Resume"
          variant="primary"
          onClick={handleResume}
          disabled={!canResume}
          pending={pending}
        />
        <ControlButton
          label="Stop"
          variant="danger"
          onClick={handleStop}
          disabled={!canStop}
          pending={pending}
        />
      </div>

      {error !== null && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}
