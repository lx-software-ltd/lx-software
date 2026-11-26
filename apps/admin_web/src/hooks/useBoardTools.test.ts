import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BoardToolsPayload } from "../lib/boardModel";
import { adminFetchJson } from "../lib/apiAdminClient";
import { BOARD_QUERY_KEY } from "./useBoard";
import { BOARD_TOOLS_KEY, toolsSaveMutationOptions } from "./useBoardTools";

vi.mock("../lib/apiAdminClient", () => ({
  adminFetchJson: vi.fn(),
}));

const fetchMock = vi.mocked(adminFetchJson);

function lastPutBody(): unknown {
  const [path, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
  expect(path).toBe("/v1/admin/siutindei/board/tools");
  expect(init?.method).toBe("PUT");
  return JSON.parse(init?.body as string);
}

describe("toolsSaveMutationOptions", () => {
  let qc: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({} as BoardToolsPayload);
    qc = new QueryClient();
  });

  it("PUTs a global-mode patch as { globalMode }", async () => {
    await toolsSaveMutationOptions(qc).mutationFn({ globalMode: "readOnly" });
    expect(lastPutBody()).toEqual({ globalMode: "readOnly" });
  });

  it("PUTs the kill switch as { enabled }", async () => {
    await toolsSaveMutationOptions(qc).mutationFn({ enabled: false });
    expect(lastPutBody()).toEqual({ enabled: false });
  });

  it("PUTs matrix patches as { matrix: { toolId: { personaId: level } } }", async () => {
    await toolsSaveMutationOptions(qc).mutationFn({
      matrix: { github: { cto: "act", cmo: "read" }, mail: { cmo: "propose" } },
    });
    expect(lastPutBody()).toEqual({
      matrix: { github: { cto: "act", cmo: "read" }, mail: { cmo: "propose" } },
    });
  });

  it("passes allow-list and spend caps through untouched", async () => {
    await toolsSaveMutationOptions(qc).mutationFn({
      allowList: ["coach@example.com", "@trusted.example"],
      spendCaps: { metaAdsDailyUsd: 20, metaAdsMonthlyUsd: 300 },
    });
    expect(lastPutBody()).toEqual({
      allowList: ["coach@example.com", "@trusted.example"],
      spendCaps: { metaAdsDailyUsd: 20, metaAdsMonthlyUsd: 300 },
    });
  });

  it("stores the saved payload and refreshes only the overview", () => {
    const spy = vi.spyOn(qc, "invalidateQueries");
    const payload = { config: { enabled: true } } as unknown as BoardToolsPayload;

    toolsSaveMutationOptions(qc).onSuccess(payload);

    expect(qc.getQueryData(BOARD_TOOLS_KEY)).toBe(payload);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({ queryKey: BOARD_QUERY_KEY, exact: true });
  });
});
