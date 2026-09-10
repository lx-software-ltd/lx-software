import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { adminFetchJson } from "../lib/apiAdminClient";
import { BOARD_WATCHLIST_KEY, watchAddMutationOptions, watchRemoveMutationOptions } from "./useBoardMarket";

vi.mock("../lib/apiAdminClient", () => ({
  adminFetchJson: vi.fn(),
}));

const fetchMock = vi.mocked(adminFetchJson);

describe("watchAddMutationOptions", () => {
  let qc: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    qc = new QueryClient();
  });

  it("posts a watch to the watchlist route", async () => {
    fetchMock.mockResolvedValueOnce({ watch: { watchId: "w1", name: "Kiztopia", kind: "competitor", urls: [] } });
    const { mutationFn } = watchAddMutationOptions(qc);
    await mutationFn({ name: "Kiztopia", kind: "competitor", urls: ["https://kiztopia.example/"] });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/siu-tin-dei/board/watchlist");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      name: "Kiztopia",
      kind: "competitor",
      urls: ["https://kiztopia.example/"],
    });
  });

  it("invalidates the watchlist after add", () => {
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { onSuccess } = watchAddMutationOptions(qc);
    onSuccess();
    expect(spy).toHaveBeenCalledWith({ queryKey: BOARD_WATCHLIST_KEY });
  });

  it("deletes a watch", async () => {
    fetchMock.mockResolvedValueOnce({ ok: true });
    const { mutationFn } = watchRemoveMutationOptions(qc);
    await mutationFn("w1");
    expect(fetchMock.mock.calls[0][0]).toBe("/siu-tin-dei/board/watchlist/w1");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("DELETE");
  });
});
