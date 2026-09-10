import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { adminFetchJson } from "../lib/apiAdminClient";
import { BOARD_PROSPECTS_KEY, prospectImportMutationOptions, prospectPutMutationOptions } from "./useBoardPipeline";

vi.mock("../lib/apiAdminClient", () => ({
  adminFetchJson: vi.fn(),
}));

const fetchMock = vi.mocked(adminFetchJson);

describe("prospect pipeline mutations", () => {
  let qc: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    qc = new QueryClient();
  });

  it("puts owner edits on the prospect route", async () => {
    fetchMock.mockResolvedValueOnce({ prospect: { prospectId: "pros-1", name: "Hall", stage: "parked" } });
    const { mutationFn } = prospectPutMutationOptions(qc);
    await mutationFn({ prospectId: "pros-1", body: { stage: "parked" } });
    expect(fetchMock.mock.calls[0][0]).toBe("/siu-tin-dei/board/prospects/pros-1");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("PUT");
  });

  it("imports CSV and invalidates the list", async () => {
    fetchMock.mockResolvedValueOnce({ created: 1, updated: 0, errors: [] });
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { mutationFn, onSuccess } = prospectImportMutationOptions(qc);
    await mutationFn("name,type,district,website,email\nHall,venue,Sha Tin,,info@h.example");
    onSuccess();
    expect(fetchMock.mock.calls[0][0]).toBe("/siu-tin-dei/board/prospects/import");
    expect(spy).toHaveBeenCalledWith({ queryKey: BOARD_PROSPECTS_KEY });
  });
});
