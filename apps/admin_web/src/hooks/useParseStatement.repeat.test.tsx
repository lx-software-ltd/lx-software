import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { HouseFinanceData } from "../lib/financeModel";
import { useParseStatement } from "./useParseStatement";

const uploadFinanceAsset = vi.hoisted(() =>
  vi.fn(async () => "uploads/admin-sub/batch/00_advice-note.pdf"),
);
const adminFetchJson = vi.hoisted(() =>
  vi.fn(async (path: string) => {
    if (path.includes("/jobs/")) {
      return {
        status: "succeeded",
        addedLines: 1,
        sourceAssetKeys: ["uploads/admin-sub/batch/00_advice-note.pdf"],
      };
    }
    return { jobId: "job-repeat", status: "pending" };
  }),
);

vi.mock("../lib/uploadFinanceAsset", () => ({
  uploadFinanceAsset,
  extractS3ErrorCode: () => null,
}));

vi.mock("../lib/apiAdminClient", () => ({
  adminFetchJson,
  getAdminApiErrorMessage: (err: unknown) =>
    err instanceof Error ? err.message : null,
}));

function houseWithImportedNote(): HouseFinanceData {
  return {
    defaultCurrency: "HKD",
    float: { amount: 0, currency: "HKD" },
    lines: [
      {
        id: "prior",
        dateUtc: "2026-09-28T04:54:00.000Z",
        type: "income",
        description: "Advice note",
        netAmount: 10,
        vat: 0,
        grossAmount: 10,
        currency: "HKD",
        sourceAssetKeys: ["inbound/morrison/prior-batch/00_advice-note.pdf"],
      },
    ],
  };
}

describe("useParseStatement repeated filename", () => {
  beforeEach(() => {
    uploadFinanceAsset.mockClear();
    adminFetchJson.mockClear();
  });

  it("uploads and starts a parse when that filename was already imported", async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    qc.setQueryData(["finance"], { morrison: houseWithImportedNote() });
    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
    }
    const file = new File([new Uint8Array([1, 2, 3])], "00_advice-note.pdf", {
      type: "application/pdf",
    });
    const { result } = renderHook(() => useParseStatement("morrison"), { wrapper });

    let addedLines = 0;
    await act(async () => {
      const parsed = await result.current.mutateAsync({ file });
      addedLines = parsed.addedLines;
    });

    expect(uploadFinanceAsset).toHaveBeenCalledTimes(1);
    expect(adminFetchJson).toHaveBeenCalled();
    expect(addedLines).toBe(1);
  });
});
