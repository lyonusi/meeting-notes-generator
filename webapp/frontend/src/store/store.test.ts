import { beforeEach, describe, expect, it } from "vitest";
import { INITIAL_SESSION_STATE, useAppStore } from "./store";
import type { AppConfig, Caption, Device, MeetingSummary } from "../types";

/**
 * Scaffold smoke tests for the store shape. These confirm the store wiring,
 * the TypeScript types, and the Vitest configuration are all functional so
 * later property/component tests have a working harness.
 */
describe("useAppStore (scaffold)", () => {
  beforeEach(() => {
    useAppStore.setState({
      recordingState: INITIAL_SESSION_STATE,
      captions: [],
      config: null,
      models: [],
      devices: [],
      meetings: [],
      openDocument: null,
      backendAvailable: true,
    });
  });

  it("starts in the idle session state with empty slices", () => {
    const s = useAppStore.getState();
    expect(s.recordingState.state).toBe("idle");
    expect(s.captions).toEqual([]);
    expect(s.config).toBeNull();
    expect(s.devices).toEqual([]);
    expect(s.meetings).toEqual([]);
    expect(s.openDocument).toBeNull();
    expect(s.backendAvailable).toBe(true);
  });

  it("updates the recording session state", () => {
    useAppStore.getState().setSessionState({
      state: "recording",
      meeting_id: "20240101_120000",
      device_id: 1,
      duration_seconds: 12.5,
      started_at: "2024-01-01T12:00:00Z",
      final_progress: null,
    });
    expect(useAppStore.getState().recordingState.state).toBe("recording");
    expect(useAppStore.getState().recordingState.meeting_id).toBe("20240101_120000");
  });

  it("replaces and clears captions", () => {
    const captions: Caption[] = [
      { start: 0, end: 1, text: "hello", status: "final" },
      { start: 1, end: 2, text: "world", status: "interim" },
    ];
    useAppStore.getState().replaceCaptions(captions);
    expect(useAppStore.getState().captions).toHaveLength(2);
    useAppStore.getState().clearCaptions();
    expect(useAppStore.getState().captions).toEqual([]);
  });

  it("stores config, devices, and meetings", () => {
    const config: AppConfig = {
      transcription_service: "whisper",
      whisper_model_size: "base",
      ai_model_id: "model-x",
      input_device_id: null,
      live_window_seconds: 5,
      live_overlap_seconds: 2,
      final_pass_max_attempts: 2,
      silence_threshold: 30,
      silence_fraction_threshold: 0.95,
    };
    const devices: Device[] = [{ id: 1, name: "Built-in Mic" }];
    const meetings: MeetingSummary[] = [
      { meeting_id: "20240101_120000", display_date: "Jan 1, 2024", title: "Standup", latest_version: 1 },
    ];

    const store = useAppStore.getState();
    store.setConfig(config);
    store.setDevices(devices);
    store.setMeetings(meetings);

    expect(useAppStore.getState().config?.transcription_service).toBe("whisper");
    expect(useAppStore.getState().devices[0].name).toBe("Built-in Mic");
    expect(useAppStore.getState().meetings[0].title).toBe("Standup");
  });
});
