/**
 * Generate structured meeting notes from a transcript using AWS Bedrock
 * (Anthropic Claude via the Messages API). Runs in the Obsidian Electron
 * renderer using the AWS SDK v3, which performs SigV4 signing in TypeScript —
 * no Python backend required.
 *
 * Credentials come from the shared AWS config (~/.aws) via the SDK's default
 * provider chain; an optional named profile can be selected in settings.
 */

import type { MeetingNotesSettings } from "./types";

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

    const { BedrockRuntimeClient, InvokeModelCommand } = await import(
      "@aws-sdk/client-bedrock-runtime"
    );
    const { fromIni } = await import("@aws-sdk/credential-providers");

    const client = new BedrockRuntimeClient({
      region: this.settings.awsRegion,
      credentials: this.settings.awsProfile
        ? fromIni({ profile: this.settings.awsProfile })
        : undefined,
    });

    const body = {
      anthropic_version: "bedrock-2023-05-31",
      max_tokens: 2000,
      messages: [
        {
          role: "user",
          content: [{ type: "text", text: buildPrompt(transcript) }],
        },
      ],
    };

    // Newer Claude models require an inference profile; the cross-region
    // "us." profile prefix is the common default in us-* regions.
    const modelId = this.resolveModelId(this.settings.bedrockModelId);

    const command = new InvokeModelCommand({
      modelId,
      contentType: "application/json",
      accept: "application/json",
      body: JSON.stringify(body),
    });

    const response = await client.send(command);
    const decoded = new TextDecoder().decode(response.body as Uint8Array);
    const payload = JSON.parse(decoded) as {
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

  /**
   * Prefix the model id with the cross-region inference-profile prefix when it
   * looks like a profile-only model. Falls back to the raw id otherwise.
   */
  private resolveModelId(modelId: string): string {
    // If the user already provided an ARN or a profile-prefixed id, use as-is.
    if (modelId.startsWith("arn:") || modelId.startsWith("us.")) return modelId;
    // Region groups map to inference-profile prefixes; us-* -> "us."
    if (this.settings.awsRegion.startsWith("us-")) return `us.${modelId}`;
    if (this.settings.awsRegion.startsWith("eu-")) return `eu.${modelId}`;
    if (this.settings.awsRegion.startsWith("ap-")) return `apac.${modelId}`;
    return modelId;
  }
}
