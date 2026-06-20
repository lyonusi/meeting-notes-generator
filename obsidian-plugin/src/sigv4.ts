/**
 * Minimal AWS Signature Version 4 signer for a single JSON POST request,
 * implemented with the Web Crypto API (`crypto.subtle`) so it works in a
 * browser-platform bundle inside Obsidian's Electron renderer.
 *
 * Scope is intentionally narrow: sign one `application/json` POST to a regional
 * service endpoint. This is all the Bedrock `InvokeModel` call needs, and it
 * lets us drop the heavyweight AWS SDK (which forces a node-platform build and
 * conflicts with onnxruntime-web).
 *
 * Reference: AWS SigV4 signing process.
 */

import type { AwsCredentials } from "./awsCredentials";

const encoder = new TextEncoder();

function toHex(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let hex = "";
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, "0");
  }
  return hex;
}

async function sha256Hex(data: string | Uint8Array): Promise<string> {
  const bytes: Uint8Array = typeof data === "string" ? encoder.encode(data) : data;
  const view = new Uint8Array(bytes); // ensure a plain ArrayBuffer backing
  const digest = await crypto.subtle.digest("SHA-256", view);
  return toHex(digest);
}

async function hmac(
  key: ArrayBuffer | Uint8Array,
  data: string,
): Promise<ArrayBuffer> {
  const keyData = new Uint8Array(key instanceof Uint8Array ? key : new Uint8Array(key));
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    keyData,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const msg = new Uint8Array(encoder.encode(data));
  return crypto.subtle.sign("HMAC", cryptoKey, msg);
}

/** YYYYMMDD'T'HHMMSS'Z' (basic ISO 8601, no separators). */
function amzDate(now: Date): { amzDate: string; dateStamp: string } {
  const iso = now.toISOString().replace(/[:-]|\.\d{3}/g, "");
  return { amzDate: iso, dateStamp: iso.slice(0, 8) };
}

export interface SignedRequest {
  url: string;
  headers: Record<string, string>;
  body: string;
}

/**
 * Build a SigV4-signed POST request.
 *
 * @param params.region   AWS region (e.g. "us-west-2")
 * @param params.service  Service name (e.g. "bedrock")
 * @param params.host     Endpoint host (e.g. "bedrock-runtime.us-west-2.amazonaws.com")
 * @param params.path     Request path (already URL-encoded)
 * @param params.body     JSON string body
 * @param params.creds    Static credentials
 */
export async function signPost(params: {
  region: string;
  service: string;
  host: string;
  path: string;
  body: string;
  creds: AwsCredentials;
}): Promise<SignedRequest> {
  const { region, service, host, path, body, creds } = params;
  const { amzDate: amz, dateStamp } = amzDate(new Date());

  const payloadHash = await sha256Hex(body);

  // Canonical headers must be sorted by lowercased name.
  const canonicalHeaders: Record<string, string> = {
    "content-type": "application/json",
    host,
    "x-amz-content-sha256": payloadHash,
    "x-amz-date": amz,
  };
  if (creds.sessionToken) {
    canonicalHeaders["x-amz-security-token"] = creds.sessionToken;
  }

  const signedHeaderNames = Object.keys(canonicalHeaders).sort();
  const canonicalHeaderString =
    signedHeaderNames.map((h) => `${h}:${canonicalHeaders[h]}`).join("\n") + "\n";
  const signedHeaders = signedHeaderNames.join(";");

  const canonicalRequest = [
    "POST",
    path,
    "", // canonical query string (none)
    canonicalHeaderString,
    signedHeaders,
    payloadHash,
  ].join("\n");

  const algorithm = "AWS4-HMAC-SHA256";
  const credentialScope = `${dateStamp}/${region}/${service}/aws4_request`;
  const stringToSign = [
    algorithm,
    amz,
    credentialScope,
    await sha256Hex(canonicalRequest),
  ].join("\n");

  // Derive the signing key.
  const kDate = await hmac(
    encoder.encode(`AWS4${creds.secretAccessKey}`),
    dateStamp,
  );
  const kRegion = await hmac(kDate, region);
  const kService = await hmac(kRegion, service);
  const kSigning = await hmac(kService, "aws4_request");
  const signature = toHex(await hmac(kSigning, stringToSign));

  const authorization =
    `${algorithm} Credential=${creds.accessKeyId}/${credentialScope}, ` +
    `SignedHeaders=${signedHeaders}, Signature=${signature}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Amz-Date": amz,
    "X-Amz-Content-Sha256": payloadHash,
    Authorization: authorization,
  };
  if (creds.sessionToken) {
    headers["X-Amz-Security-Token"] = creds.sessionToken;
  }

  return { url: `https://${host}${path}`, headers, body };
}
