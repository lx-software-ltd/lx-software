import { getAdminConfig } from "./config";
import { idTokenHasAdminAccess, readIdTokenExpiryMs } from "./jwt";

const STORAGE_ID = "lx_admin_id_token";
const STORAGE_ACCESS = "lx_admin_access_token";
const STORAGE_REFRESH = "lx_admin_refresh_token";
const STORAGE_EXPIRES_AT = "lx_admin_expires_at";

/** SessionStorage key for a one-shot login error shown on `LoginPage`. */
export const LOGIN_DENIED_FLASH_KEY = "lx_admin_login_denied_message";

export const NOT_AUTHORIZED_MESSAGE = "This account is not authorized.";

/**
 * Message for an OAuth error redirect from Cognito. The user-pool gate
 * (`backend/lambda/pre_token_generation`) refuses unlisted accounts with
 * `error_description=PreTokenGeneration failed with error This account is
 * not authorized.` (or `PreSignUp failed …`); any other error is neutral.
 */
export function loginDeniedMessage(description: string | null): string {
  if (description && /not authorized/i.test(description)) {
    return NOT_AUTHORIZED_MESSAGE;
  }
  return "Sign-in failed. Try again or contact the administrator.";
}

export interface StoredOAuthTokens {
  readonly id_token: string;
  readonly access_token: string;
  readonly refresh_token?: string;
  readonly expires_in: number;
}

export function saveTokensFromOAuthResponse(data: StoredOAuthTokens): void {
  sessionStorage.setItem(STORAGE_ID, data.id_token);
  sessionStorage.setItem(STORAGE_ACCESS, data.access_token);
  if (data.refresh_token) {
    sessionStorage.setItem(STORAGE_REFRESH, data.refresh_token);
  }
  const fromJwt = readIdTokenExpiryMs(data.id_token);
  const fromTtl = Date.now() + data.expires_in * 1000;
  const expMs = fromJwt ?? fromTtl;
  sessionStorage.setItem(STORAGE_EXPIRES_AT, String(expMs));
}

export function clearStoredSession(): void {
  sessionStorage.removeItem(STORAGE_ID);
  sessionStorage.removeItem(STORAGE_ACCESS);
  sessionStorage.removeItem(STORAGE_REFRESH);
  sessionStorage.removeItem(STORAGE_EXPIRES_AT);
  sessionStorage.removeItem("lx_admin_pkce_verifier");
  sessionStorage.removeItem("lx_admin_oauth_state");
}

export function getStoredIdToken(): string | null {
  return sessionStorage.getItem(STORAGE_ID);
}

/**
 * Returns true only when a stored ID token exists and includes the Cognito
 * `admin` group. Removes tokens that are present but not admin-eligible.
 */
export function hasAdminSession(): boolean {
  const t = getStoredIdToken();
  if (!t) {
    return false;
  }
  if (!idTokenHasAdminAccess(t)) {
    clearStoredSession();
    return false;
  }
  return true;
}

/**
 * Returns a valid ID token, refreshing with the refresh token when within
 * 60 seconds of expiry.
 */
export async function ensureFreshTokens(): Promise<string> {
  let idToken = sessionStorage.getItem(STORAGE_ID);
  if (!idToken) {
    throw new Error("Not signed in");
  }
  if (!idTokenHasAdminAccess(idToken)) {
    clearStoredSession();
    throw new Error("This account is not authorized.");
  }
  const expMs = Number(sessionStorage.getItem(STORAGE_EXPIRES_AT) || "0");
  const refreshBufferMs = 60_000;
  if (expMs > Date.now() + refreshBufferMs) {
    return idToken;
  }

  const refreshToken = sessionStorage.getItem(STORAGE_REFRESH);
  if (!refreshToken) {
    clearStoredSession();
    throw new Error("Session expired; sign in again");
  }

  const cfg = getAdminConfig();
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: cfg.clientId,
    refresh_token: refreshToken,
  });

  const res = await fetch(`${cfg.cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });

  if (!res.ok) {
    clearStoredSession();
    throw new Error("Session refresh failed");
  }

  const json = (await res.json()) as {
    id_token: string;
    access_token: string;
    expires_in: number;
    refresh_token?: string;
  };

  saveTokensFromOAuthResponse({
    id_token: json.id_token,
    access_token: json.access_token,
    refresh_token: json.refresh_token ?? refreshToken,
    expires_in: json.expires_in,
  });

  idToken = sessionStorage.getItem(STORAGE_ID);
  if (idToken && !idTokenHasAdminAccess(idToken)) {
    clearStoredSession();
    throw new Error("This account is not authorized.");
  }
  if (!idToken) {
    throw new Error("Missing ID token after refresh");
  }
  return idToken;
}
