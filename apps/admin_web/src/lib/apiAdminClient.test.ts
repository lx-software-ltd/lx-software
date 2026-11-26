import { describe, expect, it } from "vitest";
import { AdminApiError, getAdminApiErrorMessage, joinUrl, responseTextFromWire } from "./apiAdminClient";

describe("apiAdminClient joinUrl", () => {
  it("joins base and path", () => {
    expect(joinUrl("https://api.example", "/v1/admin/me")).toBe("https://api.example/v1/admin/me");
    expect(joinUrl("https://api.example/", "me")).toBe("https://api.example/me");
  });

  it("passes through absolute URLs", () => {
    expect(joinUrl("https://x", "https://y/z")).toBe("https://y/z");
  });
});

describe("responseTextFromWire", () => {
  it("passes the request path so an excluded route stays as sent", () => {
    const raw = JSON.stringify({ confirm_token: "abc", income_records: [] });
    expect(responseTextFromWire("/v1/public/newsletter/confirm/token-1?x=1", raw)).toBe(raw);
    expect(JSON.parse(responseTextFromWire("/v1/admin/finance", raw))).toEqual({
      confirmToken: "abc",
      incomeRecords: [],
    });
  });
});

describe("getAdminApiErrorMessage", () => {
  it("returns message from JSON body", () => {
    const err = new AdminApiError(400, '{"message":"expenseRecords[0].category must be one of: Utility"}');
    expect(getAdminApiErrorMessage(err)).toBe(
      "expenseRecords[0].category must be one of: Utility",
    );
  });

  it("returns null for non-AdminApiError", () => {
    expect(getAdminApiErrorMessage(new Error("network"))).toBeNull();
  });
});
