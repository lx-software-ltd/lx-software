import { ensureFreshTokens } from "./auth";
import { getAdminConfig } from "./config";
import { wireFormat } from "./contracts/generated";
import { excluded, fromWire, toWire, type WireContract } from "./wireFormat";

const CONTRACT = wireFormat as unknown as WireContract;

export class AdminApiError extends Error {
  readonly status: number;
  readonly responseBody: string;

  constructor(status: number, responseBody: string) {
    super(`Admin API request failed (${status})`);
    this.name = "AdminApiError";
    this.status = status;
    this.responseBody = responseBody;
  }
}

/** Parses API Gateway/Lambda JSON error bodies like `{ "message": "…" }`. */
export function getAdminApiErrorMessage(err: unknown): string | null {
  if (!(err instanceof AdminApiError)) return null;
  try {
    const parsed = JSON.parse(err.responseBody) as { message?: unknown };
    if (typeof parsed.message === "string" && parsed.message.trim()) {
      return parsed.message.trim();
    }
  } catch {
    /* ignore malformed JSON */
  }
  return null;
}

/** Join API base URL and path (exported for unit tests). */
export function joinUrl(base: string, path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  const prefix = base.endsWith("/") ? base.slice(0, -1) : base;
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${prefix}${suffix}`;
}

export type AdminFetchOptions = RequestInit & {
  /**
   * When false, do not attach Authorization (for public routes like GET /health).
   * Default true: always send the Cognito **ID token** (see HttpJwtAuthorizer
   * jwtAudience in CDK — ID token `aud` matches the app client; access tokens
   * do not).
   */
  readonly requireAuth?: boolean;
};

export async function adminFetch(
  path: string,
  init: AdminFetchOptions = {}
): Promise<Response> {
  const { requireAuth = true, ...rest } = init;
  // The comparison is on `import.meta.env` so Vite can drop the mock chunk when the flag is "0".
  if (import.meta.env.VITE_ADMIN_MOCK === "1") {
    const { mockAdminFetch } = await import("./mock/mockAdminApi");
    const res = await mockAdminFetch(path, rest);
    if (!res.ok) {
      throw new AdminApiError(res.status, await res.text());
    }
    return res;
  }
  const cfg = getAdminConfig();
  if (!cfg.apiBaseUrl) {
    throw new Error("VITE_API_BASE_URL is not set");
  }
  const headers = new Headers(rest.headers);
  if (requireAuth) {
    const idToken = await ensureFreshTokens();
    headers.set("Authorization", `Bearer ${idToken}`);
  }
  const skip = excluded(path, CONTRACT);
  const wirePath = skip ? path : convertQuery(path);
  let body = rest.body;
  if (!skip && typeof body === "string" && body) {
    try {
      body = JSON.stringify(toWire(JSON.parse(body), CONTRACT));
    } catch {
      // A body that is not JSON is sent unchanged.
    }
  }
  const url = joinUrl(cfg.apiBaseUrl, wirePath);
  if (!headers.has("Content-Type") && body) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(url, { ...rest, body, headers });
  const type = res.headers.get("content-type") ?? "";
  if (!skip && type.toLowerCase().includes("json")) {
    const text = await res.text();
    const converted = responseTextFromWire(path, text);
    if (!res.ok) {
      throw new AdminApiError(res.status, converted);
    }
    return new Response(converted, { status: res.status, statusText: res.statusText, headers: res.headers });
  }
  if (!res.ok) {
    const text = await res.text();
    throw new AdminApiError(res.status, text);
  }
  return res;
}

/** Decode a JSON body. ``path`` is what makes ``excludedRoutes`` apply. */
export function responseTextFromWire(path: string, text: string): string {
  const route = path.split("?")[0] ?? path;
  if (excluded(route, CONTRACT)) {
    return text;
  }
  try {
    return JSON.stringify(fromWire(JSON.parse(text), CONTRACT, route));
  } catch {
    return text;
  }
}

function convertQuery(path: string): string {
  const mark = path.indexOf("?");
  if (mark < 0) {
    return path;
  }
  const params = new URLSearchParams(path.slice(mark + 1));
  const next = new URLSearchParams();
  for (const [key, value] of params) {
    const renamed = Object.keys(toWire({ [key]: null }, CONTRACT) as Record<string, unknown>)[0] ?? key;
    next.append(renamed, value);
  }
  return `${path.slice(0, mark + 1)}${next.toString()}`;
}

export async function adminFetchJson<T>(
  path: string,
  init: AdminFetchOptions = {}
): Promise<T> {
  const res = await adminFetch(path, init);
  return (await res.json()) as T;
}

/** Presigned GET URL for a confirmed uploads/* asset (e.g. statement PDF). */
export async function fetchAssetDownloadUrl(key: string): Promise<string> {
  const data = await adminFetchJson<{ url: string }>("/v1/admin/assets/download-url", {
    method: "POST",
    body: JSON.stringify({ key }),
  });
  return data.url;
}

/** Deletes a confirmed asset from S3 and removes its DynamoDB META row. */
export async function deleteAdminAsset(key: string): Promise<void> {
  await adminFetchJson<{ ok: boolean }>("/v1/admin/assets/delete", {
    method: "POST",
    body: JSON.stringify({ key }),
  });
}
