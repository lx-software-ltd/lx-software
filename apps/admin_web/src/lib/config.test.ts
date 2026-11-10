import { afterEach, describe, expect, it, vi } from "vitest";
import { getAdminConfig } from "./config";

afterEach(() => {
  vi.unstubAllEnvs();
});

function stubSpaEnv(overrides: Record<string, string> = {}): void {
  const values: Record<string, string> = {
    VITE_COGNITO_USER_POOL_ID: "",
    VITE_COGNITO_CLIENT_ID: "client",
    VITE_COGNITO_DOMAIN: "https://auth.example/",
    VITE_COGNITO_REDIRECT_URI: "https://admin.example/auth/callback",
    VITE_API_BASE_URL: "https://api.example/",
    ...overrides,
  };
  for (const [key, value] of Object.entries(values)) {
    vi.stubEnv(key, value);
  }
}

describe("getAdminConfig", () => {
  it("builds the SPA config without a user pool id", () => {
    stubSpaEnv();
    expect(getAdminConfig()).toEqual({
      clientId: "client",
      cognitoDomain: "https://auth.example",
      redirectUri: "https://admin.example/auth/callback",
      apiBaseUrl: "https://api.example",
    });
  });

  it("rejects a missing client, domain, or redirect", () => {
    stubSpaEnv({ VITE_COGNITO_DOMAIN: "" });
    expect(() => getAdminConfig()).toThrow(/Missing Cognito/);
  });
});
