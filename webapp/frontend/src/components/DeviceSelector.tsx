/**
 * `DeviceSelector` — input-device dropdown (task 18.1).
 *
 * Renders the available audio input devices (`store.devices`) as a labelled
 * dropdown of `id + name` (Req 5.1). When the device list is empty it shows an
 * explicit empty-state message instead of an unusable control (Req 5.1).
 *
 * On change it persists the selection via `api.selectDevice(id)` and reflects
 * the new device id into the session state so the rest of the view (and the
 * eventual recording start) sees it. The control is disabled while a recording
 * is active/paused/finalizing so the device can't be swapped mid-session
 * (selection only matters while idle, Req 5.3/5.4-adjacent).
 */

import { useState } from "react";
import { api, isApiError } from "../api";
import { useAppStore } from "../store";

export default function DeviceSelector() {
  const devices = useAppStore((s) => s.devices);
  const recordingState = useAppStore((s) => s.recordingState);
  const setSessionState = useAppStore((s) => s.setSessionState);

  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Device can only be changed while idle (no active session to disrupt).
  const locked = recordingState.state !== "idle";
  const selectedId = recordingState.device_id;

  const handleChange = async (
    event: React.ChangeEvent<HTMLSelectElement>,
  ): Promise<void> => {
    const raw = event.target.value;
    if (raw === "") return;
    const deviceId = Number(raw);
    if (!Number.isFinite(deviceId)) return;

    setError(null);
    setPending(true);
    try {
      await api.selectDevice(deviceId);
      setSessionState({ ...recordingState, device_id: deviceId });
    } catch (err) {
      setError(
        isApiError(err) ? err.message : "Could not select the input device.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <label
        htmlFor="device-selector"
        className="text-xs font-semibold uppercase tracking-wide text-slate-500"
      >
        Input device
      </label>

      {devices.length === 0 ? (
        <p
          role="status"
          className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2.5 text-sm text-slate-500"
        >
          No input devices found. Connect a microphone and reload.
        </p>
      ) : (
        <select
          id="device-selector"
          value={selectedId ?? ""}
          onChange={handleChange}
          disabled={locked || pending}
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
        >
          <option value="" disabled>
            Select an input device…
          </option>
          {devices.map((device) => (
            <option key={device.id} value={device.id}>
              {device.name}
            </option>
          ))}
        </select>
      )}

      {error !== null && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}
