import { beforeEach, describe, expect, it } from "vitest";
import {
  hasAdminSession,
  loginDeniedMessage,
  NOT_AUTHORIZED_MESSAGE,
  saveTokensFromOAuthResponse,
} from "./auth";

function syntheticIdToken(payload: Record<string, unknown>): string {
  const encode = (s: string) =>
    btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${encode("{}")}.${encode(JSON.stringify(payload))}.sig`;
}

describe("loginDeniedMessage", () => {
  it("names the allow-list refusal from the Pre Token Generation gate", () => {
    expect(
      loginDeniedMessage(
        "PreTokenGeneration failed with error This account is not authorized.",
      ),
    ).toBe(NOT_AUTHORIZED_MESSAGE);
  });

  it("names the allow-list refusal from the Pre Sign-up gate", () => {
    expect(
      loginDeniedMessage(
        "PreSignUp failed with error This account is not authorized.",
      ),
    ).toBe(NOT_AUTHORIZED_MESSAGE);
  });

  it("stays neutral for any other OAuth error", () => {
    expect(loginDeniedMessage("access_denied")).not.toBe(NOT_AUTHORIZED_MESSAGE);
    expect(loginDeniedMessage(null)).not.toBe(NOT_AUTHORIZED_MESSAGE);
  });
});

describe("hasAdminSession", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("is false with no stored token", () => {
    expect(hasAdminSession()).toBe(false);
  });

  it("drops a stored token without the admin group", () => {
    saveTokensFromOAuthResponse({
      id_token: syntheticIdToken({ sub: "x", exp: 4_102_444_800 }),
      access_token: "a",
      expires_in: 3600,
    });
    expect(hasAdminSession()).toBe(false);
    expect(sessionStorage.getItem("lx_admin_id_token")).toBeNull();
  });

  it("keeps a stored token that carries the admin group", () => {
    saveTokensFromOAuthResponse({
      id_token: syntheticIdToken({
        sub: "x",
        exp: 4_102_444_800,
        "cognito:groups": ["admin"],
      }),
      access_token: "a",
      expires_in: 3600,
    });
    expect(hasAdminSession()).toBe(true);
  });
});
