import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { HouseFinanceData } from "../lib/financeModel";
import { StatementImportControl } from "./StatementImportControl";

const uploadFinanceAsset = vi.hoisted(() => vi.fn(async () => "uploads/admin-sub/batch/note.pdf"));
const adminFetchJson = vi.hoisted(() =>
  vi.fn(async (path: string) => {
    if (path.includes("/jobs/")) {
      return { status: "succeeded", addedLines: 1, sourceAssetKeys: ["uploads/admin-sub/batch/note.pdf"] };
    }
    return { jobId: "job-1", status: "pending" };
  }),
);

vi.mock("../lib/uploadFinanceAsset", () => ({
  uploadFinanceAsset,
  extractS3ErrorCode: () => null,
}));

vi.mock("../lib/apiAdminClient", () => ({
  adminFetchJson,
  getAdminApiErrorMessage: (err: unknown) => (err instanceof Error ? err.message : null),
}));

function houseWithNote(): HouseFinanceData {
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
        sourceAssetKeys: ["inbound/morrison/prior-batch/note.pdf"],
      },
    ],
  };
}

function renderControl(data: HouseFinanceData = houseWithNote()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return render(
    <StatementImportControl
      owner="morrison"
      data={data}
      title="Import statement (PDF)"
      description="Upload a statement."
      fileLabel="Statement file"
      showMortgageImport={false}
    />,
    { wrapper },
  );
}

function installDialogPolyfill() {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.open = false;
  };
}

describe("StatementImportControl repeated filename", () => {
  beforeEach(() => {
    uploadFinanceAsset.mockClear();
    adminFetchJson.mockClear();
    installDialogPolyfill();
  });

  it("asks before uploading a filename that was already imported", async () => {
    const user = userEvent.setup();
    renderControl();
    await user.click(screen.getByRole("button", { name: "Import statement (PDF)" }));
    const file = new File([new Uint8Array([1])], "note.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Statement file"), file);
    await user.click(screen.getByRole("button", { name: "Upload & parse" }));

    expect(screen.getByRole("heading", { name: "Parse this file again?" })).toBeTruthy();
    expect(uploadFinanceAsset).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(uploadFinanceAsset).not.toHaveBeenCalled();
  });

  it("parses after the operator confirms a repeated filename", async () => {
    const user = userEvent.setup();
    renderControl();
    await user.click(screen.getByRole("button", { name: "Import statement (PDF)" }));
    const file = new File([new Uint8Array([1])], "note.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Statement file"), file);
    await user.click(screen.getByRole("button", { name: "Upload & parse" }));
    await user.click(screen.getByRole("button", { name: "Parse anyway" }));

    expect(uploadFinanceAsset).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("status")).toHaveTextContent("Imported 1 statement line.");
  });

  it("uploads a new filename without asking", async () => {
    const user = userEvent.setup();
    renderControl();
    await user.click(screen.getByRole("button", { name: "Import statement (PDF)" }));
    const file = new File([new Uint8Array([1])], "fresh.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Statement file"), file);
    await user.click(screen.getByRole("button", { name: "Upload & parse" }));

    expect(screen.queryByRole("heading", { name: "Parse this file again?" })).toBeNull();
    expect(uploadFinanceAsset).toHaveBeenCalledTimes(1);
  });
});
