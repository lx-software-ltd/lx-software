import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminApiError, adminFetchJson } from "../lib/apiAdminClient";
import { DEFAULT_BOARD_BOUNDARIES } from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";
import { boundariesSaveMutationOptions } from "./useBoardBoundaries";

vi.mock("../lib/apiAdminClient", async () => {
  const actual = await vi.importActual<typeof import("../lib/apiAdminClient")>("../lib/apiAdminClient");
  return { ...actual, adminFetchJson: vi.fn() };
});

const fetchMock = vi.mocked(adminFetchJson);

describe("boundaries save mutation", () => {
  let qc: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    qc = new QueryClient();
  });

  it("sends version with the payload", async () => {
    fetchMock.mockResolvedValueOnce({ boundaries: DEFAULT_BOARD_BOUNDARIES, version: 2 });
    const { mutationFn } = boundariesSaveMutationOptions(qc);
    await mutationFn({ boundaries: DEFAULT_BOARD_BOUNDARIES, version: 1 });
    expect(fetchMock.mock.calls[0][1]?.method).toBe("PUT");
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({ version: 1 });
  });

  it("refetches the board query on 409", async () => {
    fetchMock.mockRejectedValueOnce(new AdminApiError(409, JSON.stringify({ message: "settings were updated by someone else" })));
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { mutationFn } = boundariesSaveMutationOptions(qc);
    await expect(mutationFn({ boundaries: DEFAULT_BOARD_BOUNDARIES, version: 1 })).rejects.toBeInstanceOf(AdminApiError);
    expect(spy).toHaveBeenCalledWith({ queryKey: BOARD_QUERY_KEY });
  });
});
