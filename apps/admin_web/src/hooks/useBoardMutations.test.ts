import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { adminFetchJson } from "../lib/apiAdminClient";
import { BOARD_QUERY_KEY } from "../lib/queryKeys";
import { postUpdateMutationOptions, saveCharterMutationOptions, saveSettingsMutationOptions } from "./useBoard";
import type { BoardSettings } from "../lib/boardModel";

vi.mock("../lib/apiAdminClient", () => ({
  adminFetchJson: vi.fn(),
}));

describe("board mutation options", () => {
  let qc: QueryClient;

  beforeEach(() => {
    vi.mocked(adminFetchJson).mockReset();
    qc = new QueryClient();
  });

  it("invalidates only the overview key after a charter save", () => {
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { onSuccess } = saveCharterMutationOptions(qc);
    onSuccess(
      { vision: "v", mission: "m", updatedAt: "2026-01-01T00:00:00Z" },
      { vision: "v", mission: "m" },
      undefined,
    );
    expect(spy).toHaveBeenCalledWith({ queryKey: BOARD_QUERY_KEY, exact: true });
    expect(spy).not.toHaveBeenCalledWith({ queryKey: BOARD_QUERY_KEY });
  });

  it("invalidates the overview and the updates list after a post", () => {
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { onSuccess } = postUpdateMutationOptions(qc);
    onSuccess(
      { updateId: "u1", text: "note", createdAt: "2026-01-01T00:00:00Z" },
      "note",
      undefined,
    );
    const keys = spy.mock.calls.map(([filters]) => filters);
    expect(keys).toContainEqual({ queryKey: BOARD_QUERY_KEY, exact: true });
    expect(keys).toContainEqual({ queryKey: [...BOARD_QUERY_KEY, "updates"] });
  });

  it("refreshes every board query after a settings save", () => {
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { onSuccess } = saveSettingsMutationOptions(qc);
    onSuccess({} as BoardSettings, {}, undefined);
    expect(spy).toHaveBeenCalledWith({ queryKey: BOARD_QUERY_KEY });
    expect(spy).not.toHaveBeenCalledWith({ queryKey: BOARD_QUERY_KEY, exact: true });
  });
});
