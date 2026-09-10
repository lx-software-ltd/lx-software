import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { adminFetchJson } from "../lib/apiAdminClient";
import { BOARD_QUERY_KEY } from "./useBoard";
import { BOARD_HOLDS_KEY, holdVetoMutationOptions } from "./useBoardHolds";

vi.mock("../lib/apiAdminClient", () => ({
  adminFetchJson: vi.fn(),
}));

const fetchMock = vi.mocked(adminFetchJson);

describe("holdVetoMutationOptions", () => {
  let qc: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    qc = new QueryClient();
  });

  it("posts the reason to the veto route", async () => {
    fetchMock.mockResolvedValueOnce({ hold: { holdId: "h1", status: "vetoed" } });
    const { mutationFn } = holdVetoMutationOptions(qc);
    await mutationFn({ holdId: "h1", reason: "not this week" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/siu-tin-dei/board/holds/h1/veto");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ reason: "not this week" });
  });

  it("invalidates holds and the board root", () => {
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { onSuccess } = holdVetoMutationOptions(qc);
    onSuccess();
    expect(spy).toHaveBeenCalledWith({ queryKey: BOARD_HOLDS_KEY });
    expect(spy).toHaveBeenCalledWith({ queryKey: BOARD_QUERY_KEY });
  });
});
