import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadFacebookSdk, parseSignupMessage, resetFacebookSdkForTests, startWhatsAppSignup, type FacebookSdk } from "./metaSignup";

const FACEBOOK = "https://www.facebook.com";

function report(event: string, data: Record<string, unknown>): string {
  return JSON.stringify({ type: "WA_EMBEDDED_SIGNUP", event, data });
}

describe("parseSignupMessage", () => {
  it("reads the ids from a coexistence finish", () => {
    const data = { waba_id: "111", phone_number_id: "222" };
    expect(parseSignupMessage(FACEBOOK, report("FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING", data))).toEqual({
      kind: "finished",
      wabaId: "111",
      phoneNumberId: "222",
    });
  });

  it("ignores a message that does not come from facebook.com", () => {
    const body = report("FINISH", { waba_id: "111", phone_number_id: "222" });
    expect(parseSignupMessage("https://facebook.com.example.com", body)).toBeNull();
    expect(parseSignupMessage("https://examplefacebook.com", body)).toBeNull();
    expect(parseSignupMessage("http://www.facebook.com", body)).toBeNull();
    expect(parseSignupMessage("not a url", body)).toBeNull();
    expect(parseSignupMessage("https://web.facebook.com", body)?.kind).toBe("finished");
    expect(parseSignupMessage(FACEBOOK, "not json")).toBeNull();
    expect(parseSignupMessage(FACEBOOK, JSON.stringify({ type: "other" }))).toBeNull();
  });

  it("reports a cancel, an error, and a finish without a number", () => {
    expect(parseSignupMessage(FACEBOOK, report("CANCEL", { current_step: "PHONE_NUMBER_SETUP" }))).toEqual({
      kind: "cancelled",
      step: "PHONE_NUMBER_SETUP",
    });
    expect(parseSignupMessage(FACEBOOK, report("CANCEL", { error_message: "Not eligible" }))).toEqual({
      kind: "error",
      message: "Not eligible",
    });
    expect(parseSignupMessage(FACEBOOK, report("FINISH_ONLY_WABA", { waba_id: "111" }))?.kind).toBe("error");
  });
});

describe("startWhatsAppSignup", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("asks Meta for the coexistence flow and resolves with the ids it reports", async () => {
    const login = vi.fn();
    const result = startWhatsAppSignup({ init: vi.fn(), login }, "config-9");
    expect(login.mock.calls[0][1]).toMatchObject({
      config_id: "config-9",
      response_type: "code",
      extras: { featureType: "whatsapp_business_app_onboarding", sessionInfoVersion: "3" },
    });
    window.dispatchEvent(
      new MessageEvent("message", { origin: FACEBOOK, data: report("FINISH", { waba_id: "111", phone_number_id: "222" }) }),
    );
    await expect(result).resolves.toEqual({ kind: "finished", wabaId: "111", phoneNumberId: "222" });
  });

  it("ignores a report posted by another site and keeps waiting for Meta's", async () => {
    const result = startWhatsAppSignup({ init: vi.fn(), login: vi.fn() }, "config-9");
    window.dispatchEvent(
      new MessageEvent("message", { origin: "https://www.example.com", data: report("FINISH", { waba_id: "999", phone_number_id: "888" }) }),
    );
    window.dispatchEvent(
      new MessageEvent("message", { origin: FACEBOOK, data: report("FINISH", { waba_id: "111", phone_number_id: "222" }) }),
    );
    await expect(result).resolves.toEqual({ kind: "finished", wabaId: "111", phoneNumberId: "222" });
  });

  it("resolves as cancelled when the window closes without a report", async () => {
    const login = vi.fn((callback: (response: unknown) => void) => callback({ status: "unknown" }));
    const result = startWhatsAppSignup({ init: vi.fn(), login }, "config-9");
    vi.advanceTimersByTime(2000);
    await expect(result).resolves.toEqual({ kind: "cancelled", step: "" });
  });
});

describe("loadFacebookSdk", () => {
  afterEach(() => {
    resetFacebookSdkForTests();
    delete window.FB;
    delete window.fbAsyncInit;
    document.head.querySelectorAll("script[src*='connect.facebook.net']").forEach((node) => node.remove());
  });

  it("adds the script once and initialises with the app id", async () => {
    const first = loadFacebookSdk("app-1");
    const second = loadFacebookSdk("app-1");
    expect(second).toBe(first);
    expect(document.head.querySelectorAll("script[src='https://connect.facebook.net/en_US/sdk.js']")).toHaveLength(1);
    const sdk: FacebookSdk = { init: vi.fn(), login: vi.fn() };
    window.FB = sdk;
    window.fbAsyncInit?.();
    await expect(first).resolves.toBe(sdk);
    expect(sdk.init).toHaveBeenCalledWith(expect.objectContaining({ appId: "app-1" }));
  });

  it("rejects when the script cannot load, and lets the next attempt try again", async () => {
    const attempt = loadFacebookSdk("app-1");
    const script = document.head.querySelector<HTMLScriptElement>("script[src*='connect.facebook.net']");
    script?.onerror?.(new Event("error"));
    await expect(attempt).rejects.toThrow("did not load");
    expect(loadFacebookSdk("app-1")).not.toBe(attempt);
  });
});
