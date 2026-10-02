/**
 * In-browser stand-in for the admin API, enabled with `VITE_ADMIN_MOCK=1`
 * (`npm run dev:mock`). Route handlers live under ./routes.
 */
import { saveTokensFromOAuthResponse } from "../auth";
import { isAdminMockEnabled } from "./isAdminMockEnabled";
import { notFound, resetAdminMockState, setMockStaging } from "./routes/context";
import { mockRoutes } from "./routes";
import { firstMockRoute, type MockCtx } from "./routes/types";

export { isAdminMockEnabled, resetAdminMockState, setMockStaging };

function base64Url(input: string): string {
  return btoa(input).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Unsigned JWT that satisfies the client-side admin-group check only. */
export function buildMockIdToken(): string {
  const now = Math.floor(Date.now() / 1000);
  const header = base64Url(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64Url(
    JSON.stringify({
      sub: "mock-admin",
      email: "mock.admin@example.com",
      "cognito:groups": ["admin"],
      iat: now,
      auth_time: now,
      exp: now + 12 * 3600,
    }),
  );
  return `${header}.${payload}.mock`;
}

export function installAdminMockSession(): void {
  saveTokensFromOAuthResponse({
    id_token: buildMockIdToken(),
    access_token: "mock-access",
    refresh_token: "mock-refresh",
    expires_in: 12 * 3600,
  });
}


export async function mockAdminFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const url = new URL(path, "http://mock.local");
  const ctx: MockCtx = { method, url, path: url.pathname, init };
  return firstMockRoute(mockRoutes, ctx) ?? notFound(url.pathname);
}
