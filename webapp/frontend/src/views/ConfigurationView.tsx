/**
 * ConfigurationView (task 19.1).
 *
 * The settings panel for the live-transcription web UI. It lets the user pick:
 *
 * - the transcription service from exactly `whisper | aws | mac` (Req 6.1),
 * - the whisper model size from exactly `tiny | base | small | medium | large`,
 *   enabled if and only if the selected service is `whisper` (Req 6.3, 6.4),
 * - the AI model used for notes generation, from the backend-provided list
 *   (Req 6.5).
 *
 * On mount it loads the applied configuration (`api.getConfig`) and the model
 * list (`api.listModels`) into the store, then pre-selects the most recently
 * applied values (Req 6.2). Changes auto-apply through `api.updateConfig`; on
 * success the store config is updated and a "saved" indicator is shown, and on
 * a rejected value (`ApiError`, e.g. 422 invalid_config) an inline error is
 * shown and the previous selection is kept (Req 6.7).
 *
 * Scope: this file implements ONLY the configuration view. The app shell /
 * router lives in task 22.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  TRANSCRIPTION_SERVICE_IDS,
  WHISPER_MODEL_SIZES,
  type AppConfig,
  type TranscriptionServiceId,
  type WhisperModelSize,
} from "../types";
import { useAppStore } from "../store";
import {
  getConfig,
  listModels,
  updateConfig,
  isApiError,
  type ConfigUpdateRequest,
} from "../api";

/** Human-readable labels for each transcription service option. */
const SERVICE_LABELS: Record<TranscriptionServiceId, string> = {
  whisper: "Whisper (local faster-whisper)",
  aws: "AWS Transcribe",
  mac: "macOS Speech",
};

/** Human-readable labels for each whisper model size option. */
const MODEL_SIZE_LABELS: Record<WhisperModelSize, string> = {
  tiny: "Tiny",
  base: "Base",
  small: "Small",
  medium: "Medium",
  large: "Large",
};

/** The transient status of the most recent auto-apply attempt. */
type SaveStatus = "idle" | "saving" | "saved" | "failed";

/** Props for {@link ConfigurationView}. */
export interface ConfigurationViewProps {
  /**
   * When true, drop the standalone `mx-auto max-w-2xl` centering so the view
   * fills a narrow container (e.g. the Record page's settings drawer). Outer
   * padding is preserved. Defaults to `false` to keep standalone behaviour.
   */
  embedded?: boolean;
}

export default function ConfigurationView({
  embedded = false,
}: ConfigurationViewProps = {}) {
  const config = useAppStore((s) => s.config);
  const models = useAppStore((s) => s.models);
  const setConfig = useAppStore((s) => s.setConfig);
  const setModels = useAppStore((s) => s.setModels);

  /** Whether the initial config/models load is still in flight. */
  const [loading, setLoading] = useState(true);
  /** A load-time error message (config/models fetch failed), or null. */
  const [loadError, setLoadError] = useState<string | null>(null);
  /** The status of the latest save (auto-apply) attempt. */
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  /** An inline error from a rejected update (Req 6.7), or null. */
  const [updateError, setUpdateError] = useState<string | null>(null);

  /** Avoid clobbering store config across unmounts mid-flight. */
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // On mount: load applied config -> store, and models -> store (if absent).
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function load() {
      setLoading(true);
      setLoadError(null);
      try {
        // Always refresh the applied config so the view reflects the latest
        // applied values (Req 6.2). Load models only if not already present.
        const [loadedConfig, loadedModels] = await Promise.all([
          getConfig(controller.signal),
          models.length === 0
            ? listModels(controller.signal)
            : Promise.resolve(models),
        ]);
        if (cancelled || !mountedRef.current) return;
        setConfig(loadedConfig);
        if (models.length === 0) {
          setModels(loadedModels);
        }
      } catch (err) {
        if (cancelled || !mountedRef.current) return;
        // Ignore aborts; surface everything else as a load error.
        if (err instanceof DOMException && err.name === "AbortError") return;
        const message = isApiError(err)
          ? err.message
          : "Could not load configuration.";
        setLoadError(message);
      } finally {
        if (!cancelled && mountedRef.current) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
    // Intentionally run once on mount. `models`/setters are stable enough for
    // this one-shot load; re-running on every model change is undesirable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The whisper-model-size control is enabled iff the service is whisper
  // (Req 6.4, Property 15).
  const whisperEnabled = config?.transcription_service === "whisper";

  /**
   * Apply a config patch via the backend. On success update the store and show
   * a "saved" indicator; on an ApiError (rejected value, Req 6.7) show an
   * inline error and keep the previous selection (do not update the store).
   */
  async function applyPatch(patch: ConfigUpdateRequest) {
    setUpdateError(null);
    setSaveStatus("saving");
    try {
      const updated: AppConfig = await updateConfig(patch);
      if (!mountedRef.current) return;
      setConfig(updated);
      setSaveStatus("saved");
    } catch (err) {
      if (!mountedRef.current) return;
      // Keep the previously applied selection; surface the rejection inline.
      const message = isApiError(err)
        ? err.message
        : "Could not apply the configuration change.";
      setUpdateError(message);
      setSaveStatus("failed");
    }
  }

  function handleServiceChange(value: string) {
    // `value` always comes from the rendered option set, so it is valid; the
    // cast narrows it back to the union for the typed patch.
    applyPatch({ transcription_service: value as TranscriptionServiceId });
  }

  function handleModelSizeChange(value: string) {
    applyPatch({ whisper_model_size: value as WhisperModelSize });
  }

  function handleAiModelChange(value: string) {
    applyPatch({ ai_model_id: value });
  }

  // The AI model select pre-selects config.ai_model_id. If the applied model
  // is not in the list (e.g. backend changed), still show it as a fallback
  // option so the current value is visible.
  const aiModelOptions = useMemo(() => {
    if (!config) return models;
    const present = models.some((m) => m.id === config.ai_model_id);
    if (present || !config.ai_model_id) return models;
    return [{ id: config.ai_model_id, name: config.ai_model_id }, ...models];
  }, [config, models]);

  // Outer wrapper width: standalone centers within a max width; embedded fills
  // its (narrow) container with consistent padding.
  const outerClass = embedded ? "w-full p-4" : "mx-auto max-w-2xl p-6";

  if (loading) {
    return (
      <section className={outerClass}>
        <p className="text-sm text-slate-500">Loading configuration…</p>
      </section>
    );
  }

  if (loadError || !config) {
    return (
      <section className={outerClass}>
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {loadError ?? "Configuration is unavailable."}
        </div>
      </section>
    );
  }

  return (
    <section
      className={
        embedded ? "w-full space-y-6 p-4" : "mx-auto max-w-2xl space-y-6 p-6"
      }
    >
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Configuration</h2>
          <p className="mt-1 text-sm text-slate-500">
            Choose how meetings are transcribed and which AI model generates notes.
          </p>
        </div>
        <SaveIndicator status={saveStatus} />
      </header>

      {updateError && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {updateError}
        </div>
      )}

      <div className="space-y-5 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        {/* Transcription service (Req 6.1) */}
        <FieldRow
          label="Transcription service"
          htmlFor="transcription-service"
          hint="Engine used for the final, authoritative transcript."
        >
          <select
            id="transcription-service"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
            value={config.transcription_service}
            onChange={(e) => handleServiceChange(e.target.value)}
          >
            {TRANSCRIPTION_SERVICE_IDS.map((id) => (
              <option key={id} value={id}>
                {SERVICE_LABELS[id]}
              </option>
            ))}
          </select>
        </FieldRow>

        {/* Whisper model size — enabled iff service is whisper (Req 6.3, 6.4) */}
        <FieldRow
          label="Whisper model size"
          htmlFor="whisper-model-size"
          hint={
            whisperEnabled
              ? "Larger models are more accurate but slower."
              : "Available only when the transcription service is Whisper."
          }
        >
          <select
            id="whisper-model-size"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
            value={config.whisper_model_size}
            disabled={!whisperEnabled}
            onChange={(e) => handleModelSizeChange(e.target.value)}
          >
            {WHISPER_MODEL_SIZES.map((size) => (
              <option key={size} value={size}>
                {MODEL_SIZE_LABELS[size]}
              </option>
            ))}
          </select>
        </FieldRow>

        {/* AI model (Req 6.5) */}
        <FieldRow
          label="AI model"
          htmlFor="ai-model"
          hint="Model used by the notes generator."
        >
          <select
            id="ai-model"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
            value={config.ai_model_id}
            disabled={aiModelOptions.length === 0}
            onChange={(e) => handleAiModelChange(e.target.value)}
          >
            {aiModelOptions.length === 0 ? (
              <option value="">No models available</option>
            ) : (
              aiModelOptions.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name}
                </option>
              ))
            )}
          </select>
        </FieldRow>
      </div>
    </section>
  );
}

/** A labeled settings field: label + hint on the left, control below. */
function FieldRow({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label
        htmlFor={htmlFor}
        className="block text-sm font-medium text-slate-700"
      >
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

/** A small inline indicator reflecting the auto-apply status. */
function SaveIndicator({ status }: { status: SaveStatus }) {
  if (status === "idle") return null;

  const config: Record<
    Exclude<SaveStatus, "idle">,
    { text: string; className: string }
  > = {
    saving: {
      text: "Saving…",
      className: "bg-slate-100 text-slate-600",
    },
    saved: {
      text: "Saved",
      className: "bg-emerald-50 text-emerald-700 border border-emerald-200",
    },
    failed: {
      text: "Not saved",
      className: "bg-red-50 text-red-700 border border-red-200",
    },
  };

  const { text, className } = config[status];
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${className}`}
    >
      {text}
    </span>
  );
}
