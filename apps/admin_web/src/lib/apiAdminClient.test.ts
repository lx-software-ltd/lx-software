import { describe, expect, it } from "vitest";
import { AdminApiError, getAdminApiErrorMessage, joinUrl } from "./apiAdminClient";

describe("apiAdminClient joinUrl", () => {
  it("joins base and path", () => {
    expect(joinUrl("https://api.example", "/v1/admin/me")).toBe("https://api.example/v1/admin/me");
    expect(joinUrl("https://api.example/", "me")).toBe("https://api.example/me");
  });

  it("passes through absolute URLs", () => {
    expect(joinUrl("https://x", "https://y/z")).toBe("https://y/z");
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
