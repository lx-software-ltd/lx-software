import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminApiError, adminFetchJson } from "../lib/apiAdminClient";
import { postStaffTick, staffTickErrorMessage } from "./useBoardStaff";

vi.mock("../lib/apiAdminClient", async () => {
  const actual = await vi.importActual<typeof import("../lib/apiAdminClient")>("../lib/apiAdminClient");
  return { ...actual, adminFetchJson: vi.fn() };
});

const fetchMock = vi.mocked(adminFetchJson);

describe("staffTickErrorMessage", () => {
  it("explains a 404 when the Lambda has not been redeployed", () => {
    const err = new AdminApiError(404, JSON.stringify({ message: "Unknown staff seat" }));
    expect(staffTickErrorMessage(err)).toMatch(/Deploy Backend/);
  });

  it("does not special-case TypeError — the mutation treats that as queued", () => {
    expect(staffTickErrorMessage(new TypeError("Load failed"))).toBe("Load failed");
  });

  it("passes through a JSON API message", () => {
    const err = new AdminApiError(409, JSON.stringify({ message: "Staff is disabled" }));
    expect(staffTickErrorMessage(err)).toBe("Staff is disabled");
  });
});

describe("postStaffTick", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("POSTs with no body", async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, queued: true, invoked: true });
    await postStaffTick();
    expect(fetchMock).toHaveBeenCalledWith("/siu-tin-dei/board/staff/tick", { method: "POST" });
  });

  it("retries a dropped fetch once", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Load failed"));
    fetchMock.mockResolvedValueOnce({ ok: true, queued: true, invoked: true });
    const result = await postStaffTick();
    expect(result.invoked).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("treats two dropped fetches as queued", async () => {
    fetchMock.mockRejectedValue(new TypeError("Load failed"));
    const result = await postStaffTick();
    expect(result).toEqual({ ok: true, queued: true, droppedByBrowser: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
