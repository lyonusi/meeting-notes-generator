/**
 * Audio capture via the Web Audio API (available inside Obsidian's Electron
 * renderer). Captures from a chosen input device, accumulates mono PCM at the
 * Whisper sample rate, and exposes the buffer for windowed + final transcription.
 *
 * System/meeting audio capture requires a loopback device (e.g. BlackHole on
 * macOS) selected as the input — same constraint as the desktop app.
 */

import { WHISPER_SAMPLE_RATE } from "./transcriber";

export interface InputDevice {
  /** MediaDeviceInfo.deviceId */
  id: string;
  /** Human-readable label. */
  label: string;
}

export class Recorder {
  private stream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private processorNode: ScriptProcessorNode | null = null;

  /** Accumulated mono samples at the AudioContext sample rate. */
  private chunks: Float32Array[] = [];
  private capturedSampleRate = WHISPER_SAMPLE_RATE;
  private recording = false;
  private paused = false;

  get isRecording(): boolean {
    return this.recording;
  }

  get isPaused(): boolean {
    return this.paused;
  }

  /** Enumerate available audio input devices (labels require a prior permission grant). */
  static async listInputDevices(): Promise<InputDevice[]> {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices
      .filter((d) => d.kind === "audioinput")
      .map((d, i) => ({
        id: d.deviceId,
        label: d.label || `Microphone ${i + 1}`,
      }));
  }

  /** Begin capturing from the given device (or the default input when omitted). */
  async start(deviceId?: string): Promise<void> {
    if (this.recording) return;

    const constraints: MediaStreamConstraints = {
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
      video: false,
    };
    this.stream = await navigator.mediaDevices.getUserMedia(constraints);

    this.audioContext = new AudioContext();
    this.capturedSampleRate = this.audioContext.sampleRate;
    this.sourceNode = this.audioContext.createMediaStreamSource(this.stream);

    // ScriptProcessorNode is deprecated but universally available in Electron
    // and simplest for raw PCM capture; buffer size 4096 is a good balance.
    this.processorNode = this.audioContext.createScriptProcessor(4096, 1, 1);
    this.processorNode.onaudioprocess = (event) => {
      if (!this.recording || this.paused) return;
      const input = event.inputBuffer.getChannelData(0);
      // Copy — the underlying buffer is reused by the audio thread.
      this.chunks.push(new Float32Array(input));
    };

    this.sourceNode.connect(this.processorNode);
    // Connect to destination (muted) so the processor actually runs.
    this.processorNode.connect(this.audioContext.destination);

    this.chunks = [];
    this.recording = true;
    this.paused = false;
  }

  pause(): void {
    if (this.recording) this.paused = true;
  }

  resume(): void {
    if (this.recording) this.paused = false;
  }

  /** Stop capture and release devices. Returns the full mono buffer at 16 kHz. */
  async stop(): Promise<Float32Array> {
    this.recording = false;
    this.paused = false;

    this.processorNode?.disconnect();
    this.sourceNode?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    const ctx = this.audioContext;
    this.processorNode = null;
    this.sourceNode = null;
    this.stream = null;

    const merged = this.mergeChunks();
    const resampled = this.resampleTo16k(merged, this.capturedSampleRate);

    if (ctx) await ctx.close();
    this.audioContext = null;
    return resampled;
  }

  /**
   * Snapshot the audio captured so far, resampled to 16 kHz mono. Used by the
   * live windowing loop without stopping the recording.
   */
  snapshot16k(): Float32Array {
    const merged = this.mergeChunks();
    return this.resampleTo16k(merged, this.capturedSampleRate);
  }

  /** Peak absolute amplitude over the captured buffer (for silence detection). */
  peakAmplitude(): number {
    let peak = 0;
    for (const chunk of this.chunks) {
      for (let i = 0; i < chunk.length; i++) {
        const a = Math.abs(chunk[i]);
        if (a > peak) peak = a;
      }
    }
    return peak;
  }

  private mergeChunks(): Float32Array {
    let total = 0;
    for (const c of this.chunks) total += c.length;
    const out = new Float32Array(total);
    let offset = 0;
    for (const c of this.chunks) {
      out.set(c, offset);
      offset += c.length;
    }
    return out;
  }

  /** Linear-interpolation resample to 16 kHz (sufficient for speech/Whisper). */
  private resampleTo16k(input: Float32Array, inputRate: number): Float32Array {
    if (input.length === 0) return input;
    if (inputRate === WHISPER_SAMPLE_RATE) return input;
    const ratio = WHISPER_SAMPLE_RATE / inputRate;
    const outLength = Math.round(input.length * ratio);
    const output = new Float32Array(outLength);
    for (let i = 0; i < outLength; i++) {
      const srcPos = i / ratio;
      const i0 = Math.floor(srcPos);
      const i1 = Math.min(i0 + 1, input.length - 1);
      const frac = srcPos - i0;
      output[i] = input[i0] * (1 - frac) + input[i1] * frac;
    }
    return output;
  }
}
