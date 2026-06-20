/**
 * Minimal AWS credential resolver.
 *
 * Reads static credentials from the shared files (`~/.aws/credentials` and
 * `~/.aws/config`) for a named profile, plus an optional `region`. This avoids
 * the heavy AWS SDK; Obsidian runs in Electron where Node's `fs`/`os` are
 * available even in a browser-platform build.
 *
 * Supported per profile: `aws_access_key_id`, `aws_secret_access_key`,
 * `aws_session_token` (optional), and `region`. SSO / process / role-assumption
 * credential sources are NOT supported (use static keys for this plugin).
 */

export interface AwsCredentials {
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken?: string;
  region?: string;
}

/** Parse a very small subset of the INI format used by AWS config files. */
function parseIni(text: string): Record<string, Record<string, string>> {
  const sections: Record<string, Record<string, string>> = {};
  let current: string | null = null;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.replace(/[;#].*$/, "").trim();
    if (!line) continue;
    const sectionMatch = line.match(/^\[(.+)\]$/);
    if (sectionMatch) {
      // In ~/.aws/config profiles are written as "[profile name]"; in
      // ~/.aws/credentials they are just "[name]". Normalize both to the name.
      current = sectionMatch[1].replace(/^profile\s+/, "").trim();
      sections[current] = sections[current] ?? {};
      continue;
    }
    if (!current) continue;
    const eq = line.indexOf("=");
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).trim();
    sections[current][key] = value;
  }
  return sections;
}

function readFileSafe(path: string): string | null {
  try {
    // Lazy require so a browser-platform bundle doesn't hard-fail at import;
    // Electron provides Node's fs at runtime.
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const fs = require("fs") as typeof import("fs");
    return fs.readFileSync(path, "utf-8");
  } catch {
    return null;
  }
}

function homeDir(): string {
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const os = require("os") as typeof import("os");
    return os.homedir();
  } catch {
    return process.env.HOME ?? "";
  }
}

/**
 * Resolve static credentials for `profile` from `~/.aws/credentials` (preferred
 * for keys) and `~/.aws/config` (for region / fallback). Returns null when no
 * access key can be found.
 */
export function resolveAwsCredentials(
  profile: string,
  fallbackRegion?: string,
): AwsCredentials | null {
  const home = homeDir();
  if (!home) return null;

  const credText = readFileSafe(`${home}/.aws/credentials`);
  const configText = readFileSafe(`${home}/.aws/config`);

  const creds = credText ? parseIni(credText) : {};
  const config = configText ? parseIni(configText) : {};

  const name = profile || "default";
  const credSection = creds[name] ?? {};
  const configSection = config[name] ?? {};

  const accessKeyId =
    credSection["aws_access_key_id"] ?? configSection["aws_access_key_id"];
  const secretAccessKey =
    credSection["aws_secret_access_key"] ??
    configSection["aws_secret_access_key"];
  if (!accessKeyId || !secretAccessKey) return null;

  const sessionToken =
    credSection["aws_session_token"] ?? configSection["aws_session_token"];
  const region =
    configSection["region"] ?? credSection["region"] ?? fallbackRegion;

  return {
    accessKeyId,
    secretAccessKey,
    sessionToken: sessionToken || undefined,
    region: region || undefined,
  };
}
