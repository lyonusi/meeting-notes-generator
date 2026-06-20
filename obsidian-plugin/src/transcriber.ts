/**
 * Local Whisper transcription via transformers.js (WASM), with rolling
 * overlapping windows so captions appear while recording (live-ish).
 *
 * The model is downloaded once from the Hugging Face hub and cached by
 * transformers.js. All inference runs in-process (WASM) — no network call per
 * transcription and no Python dependency.
 */

import type { Caption, WhisperModelSize } from "./types";

// transformers.js is imported lazily so plugin load is fast and the (large)
// model is only pulled when the user first records.
type Pipeline = (audio: Float32Array, options?: Record<string, unknown>) => Promise<{
  text: string;
  chunks?: Array<{ timestamp: [number, number | null]; text: string }>;
}>;

const MODEL_IDS: Record<WhisperModelSize, string> = {
  tiny: "Xenova/whisper-tiny",
  base: "Xenova/whisper-base",
  small: "Xenova/whisper-small",
};

/** Whisper expects 16 kHz mono float32 audio. */
export const WHISPER_SAMPLE_RATE = 16000;

export class Transcriber {
  private modelSize: WhisperModelSize;
  private pipelinePromise: Promise<Pipeline> | null = null;

  constructor(modelSize: WhisperModelSize) {
    this.modelSize = modelSize;
  }

  /** Returns true once the model pipeline has been (or is being) loaded. */
  get isLoading(): boolean {
    return this.pipelinePromise !== null;
  }

  /**
   * Lazily build the ASR pipeline. Safe to call repeatedly; the same promise is
   * reused. Reports load progress via the optional callback.
   */
  async load(
    onProgress?: (message: string) => void,
  ): Promise<Pipeline> {
    if (this.pipelinePromise) return this.pipelinePromise;

    this.pipelinePromise = (async () => {
      onProgress?.(`Loading Whisper (${this.modelSize})…`);
      // Lazy dynamic import keeps the heavy dependency out of the initial bundle
      // evaluation and lets esbuild resolve it at build time.
      const { pipeline, env } = await import("@xenova/transformers");
      // Use the remote hub model; cache in the browser (IndexedDB) by default.
      env.allowLocalModels = false;
      const asr = (await pipeline(
        "automatic-speech-recognition",
        MODEL_IDS[this.modelSize],
        {
          progress_callback: (p: { status?: string; progress?: number }) => {
            if (p.status === "progress" && typeof p.progress === "number") {
              onProgress?.(`Downloading model… ${Math.round(p.progress)}%`);
            }
          },
        },
      )) as unknown as Pipeline;
      onProgress?.("Whisper ready.");
      return asr;
    })();

    return this.pipelinePromise;
  }

  /**
   * Transcribe a complete mono Float32 buffer (16 kHz) into captions with
   * word/segment timestamps. Used both for live windows and the final pass.
   *
   * @param audio mono float32 samples at {@link WHISPER_SAMPLE_RATE}
   * @param offsetSeconds added to every segment timestamp so a windowed chunk
   *        maps back to absolute recording time
   * @param status the status to stamp on produced captions
   */
  async transcribe(
    audio: Float32Array,
    offsetSeconds = 0,
    status: Caption["status"] = "final",
  ): Promise<Caption[]> {
    if (audio.length === 0) return [];
    const asr = await this.load();
    const result = await asr(audio, {
      // Return per-segment timestamps so captions can be placed in time.
      return_timestamps: true,
      chunk_length_s: 30,
      stride_length_s: 5,
    });

    const chunks = result.chunks ?? [];
    if (chunks.length === 0) {
      const text = (result.text ?? "").trim();
      if (!text) return [];
      return [
        {
          start: offsetSeconds,
          end: offsetSeconds,
          text,
          status,
        },
      ];
    }

    const captions: Caption[] = [];
    for (const chunk of chunks) {
      const text = (chunk.text ?? "").trim();
      if (!text) continue;
      const [s, e] = chunk.timestamp;
      const start = offsetSeconds + (typeof s === "number" ? s : 0);
      const end = offsetSeconds + (typeof e === "number" ? e : start);
      captions.push({ start, end: Math.max(start, end), text, status });
    }
    return captions;
  }
}
