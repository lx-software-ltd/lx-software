import { ensureFreshTokens } from "./auth";
import { getAdminConfig } from "./config";

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
  const url = joinUrl(cfg.apiBaseUrl, path);
  if (!headers.has("Content-Type") && rest.body) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(url, { ...rest, headers });
  if (!res.ok) {
    const text = await res.text();
    throw new AdminApiError(res.status, text);
  }
  return res;
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
  const data = await adminFetchJson<{ url: string }>("/assets/download-url", {
    method: "POST",
    body: JSON.stringify({ key }),
  });
  return data.url;
}

/** Deletes a confirmed asset from S3 and removes its DynamoDB META row. */
export async function deleteAdminAsset(key: string): Promise<void> {
  await adminFetchJson<{ ok: boolean }>("/assets/delete", {
    method: "POST",
    body: JSON.stringify({ key }),
  });
}
