import { describe, expect, it } from "vitest";
import { AdminApiError } from "../lib/apiAdminClient";
import { staffTickErrorMessage } from "./useBoardStaff";

describe("staffTickErrorMessage", () => {
  it("explains a 404 when the Lambda has not been redeployed", () => {
    const err = new AdminApiError(404, JSON.stringify({ message: "Unknown staff seat" }));
    expect(staffTickErrorMessage(err)).toMatch(/Deploy Backend/);
  });

  it("explains Safari Load failed", () => {
    expect(staffTickErrorMessage(new TypeError("Load failed"))).toMatch(/Load failed/);
  });

  it("passes through a JSON API message", () => {
    const err = new AdminApiError(409, JSON.stringify({ message: "Staff is disabled" }));
    expect(staffTickErrorMessage(err)).toBe("Staff is disabled");
  });
});
