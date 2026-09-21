import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { adminFetchJson } from "../lib/apiAdminClient";
import { catalogBulkDecideMutationOptions, catalogDecideMutationOptions } from "./useBoardCatalog";

vi.mock("../lib/apiAdminClient", () => ({
  adminFetchJson: vi.fn(),
}));

const fetchMock = vi.mocked(adminFetchJson);

describe("catalog candidate mutations", () => {
  let qc: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    qc = new QueryClient();
  });

  it("posts a single approve", async () => {
    fetchMock.mockResolvedValueOnce({ candidate: { candidateId: "c1", status: "approved" } });
    const { mutationFn } = catalogDecideMutationOptions(qc);
    await mutationFn({ candidateId: "c1", decision: "approve" });
    expect(fetchMock).toHaveBeenCalledWith("/siu-tin-dei/board/catalog/candidates/c1/approve", {
      method: "POST",
      body: JSON.stringify({}),
    });
  });

  it("posts a bulk close with leftover-competitor filters", async () => {
    fetchMock.mockResolvedValueOnce({ updated: 3, status: "closed" });
    const { mutationFn } = catalogBulkDecideMutationOptions(qc);
    await mutationFn({
      decision: "close",
      source: "competitor",
      status: "new",
      before: "2026-09-14T00:00:00Z",
      missingPlaceId: true,
    });
    expect(fetchMock).toHaveBeenCalledWith("/siu-tin-dei/board/catalog/candidates/bulk", {
      method: "POST",
      body: JSON.stringify({
        decision: "close",
        source: "competitor",
        status: "new",
        before: "2026-09-14T00:00:00Z",
        missingPlaceId: true,
      }),
    });
  });
});
