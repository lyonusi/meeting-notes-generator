/**
 * Generate structured meeting notes from a transcript using AWS Bedrock
 * (Anthropic Claude via the Messages API).
 *
 * Instead of the heavyweight AWS SDK (which forces a node-platform bundle and
 * conflicts with onnxruntime-web), this signs a single SigV4 POST with Web
 * Crypto and sends it via Obsidian's `requestUrl` (which bypasses browser CORS
 * restrictions in the Electron renderer).
 */

import { requestUrl } from "obsidian";
import type { MeetingNotesSettings } from "./types";
import { resolveAwsCredentials } from "./awsCredentials";
import { signPost } from "./sigv4";

/** The prompt mirrors the desktop app's notes structure. */
function buildPrompt(transcript: string): string {
  return [
    "You are an expert meeting-notes assistant. Given the raw transcript of a",
    "meeting, produce clear, well-structured Markdown notes with these sections:",
    "",
    "# Meeting Notes",
    "## Summary  (2-4 sentences)",
    "## Key Discussion Points  (bulleted)",
    "## Decisions  (bulleted; omit if none)",
    "## Action Items  (bulleted; include owner and due date when stated)",
    "",
    "Be faithful to the transcript; do not invent facts. If the transcript is",
    "short or unclear, produce a brief best-effort summary.",
    "",
    "Transcript:",
    '"""',
    transcript,
    '"""',
  ].join("\n");
}

export class NotesGenerator {
  private settings: MeetingNotesSettings;

  constructor(settings: MeetingNotesSettings) {
    this.settings = settings;
  }

  /**
   * Generate notes Markdown from a transcript. Throws on failure so the caller
   * can surface a real error (rather than silently returning a placeholder).
   */
  async generate(transcript: string): Promise<string> {
    if (!transcript.trim()) {
      throw new Error("Cannot generate notes from an empty transcript.");
    }

    const region = this.settings.awsRegion || "us-west-2";
    const creds = resolveAwsCredentials(this.settings.awsProfile, region);
    if (!creds) {
      throw new Error(
        `No AWS credentials found for profile "${this.settings.awsProfile}". ` +
          "Add static keys to ~/.aws/credentials.",
      );
    }
    const effectiveRegion = creds.region || region;

    const modelId = this.resolveModelId(this.settings.bedrockModelId, effectiveRegion);
    const host = `bedrock-runtime.${effectiveRegion}.amazonaws.com`;
    const path = `/model/${encodeURIComponent(modelId)}/invoke`;

    const body = JSON.stringify({
      anthropic_version: "bedrock-2023-05-31",
      max_tokens: 2000,
      messages: [
        { role: "user", content: [{ type: "text", text: buildPrompt(transcript) }] },
      ],
    });

    const signed = await signPost({
      region: effectiveRegion,
      service: "bedrock",
      host,
      path,
      body,
      creds,
    });

    const response = await requestUrl({
      url: signed.url,
      method: "POST",
      headers: signed.headers,
      body: signed.body,
      throw: false,
    });

    if (response.status < 200 || response.status >= 300) {
      const detail = this.extractError(response.text);
      throw new Error(`Bedrock returned ${response.status}: ${detail}`);
    }

    const payload = response.json as {
      content?: Array<{ type: string; text?: string }>;
    };
    const text = (payload.content ?? [])
      .filter((c) => c.type === "text" && c.text)
      .map((c) => c.text as string)
      .join("\n")
      .trim();

    if (!text) {
      throw new Error("Bedrock returned an empty response.");
    }
    return text;
  }

  /** Pull a human-readable message out of a Bedrock error body, if present. */
  private extractError(text: string): string {
    try {
      const obj = JSON.parse(text) as { message?: string; Message?: string };
      return obj.message ?? obj.Message ?? text;
    } catch {
      return text || "unknown error";
    }
  }

  /**
   * Prefix the model id with the cross-region inference-profile prefix when it
   * looks like a profile-only model. Falls back to the raw id otherwise.
   */
  private resolveModelId(modelId: string, region: string): string {
    if (modelId.startsWith("arn:") || /^(us|eu|apac)\./.test(modelId)) return modelId;
    if (region.startsWith("us-")) return `us.${modelId}`;
    if (region.startsWith("eu-")) return `eu.${modelId}`;
    if (region.startsWith("ap-")) return `apac.${modelId}`;
    return modelId;
  }
}
