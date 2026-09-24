import { MemoryRouter } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_FINANCE_STATE } from "../lib/financeModel";
import { FinancePage } from "./FinancePage";

const financeMock = {
  data: DEFAULT_FINANCE_STATE,
  patchHouse: vi.fn(),
  patchLedgerRecords: vi.fn(),
  patchInvestmentRecords: vi.fn(),
  patchSavingsRecords: vi.fn(),
  patchPensionRecords: vi.fn(),
  patchAllocationRecords: vi.fn(),
  patchAccountRecords: vi.fn(),
  patchLiabilityRecords: vi.fn(),
  patchExpenseIncomeAllocationPercents: vi.fn(),
  isLoading: false,
  isError: true,
  isRefetching: false,
  refetch: vi.fn(),
  isSaving: false,
  saveError: null,
  saveErrorDetail: null,
};

vi.mock("../hooks/useFinance", () => ({
  useFinance: () => financeMock,
}));

describe("FinancePage error gate", () => {
  it("does not render editable panels when the finance query failed", () => {
    render(
      <MemoryRouter>
        <FinancePage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load finance data");
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add record" })).toBeNull();
    expect(screen.queryByLabelText("Description")).toBeNull();
    expect(
      screen.getByText(/Records could not be loaded, so editing is paused/),
    ).toBeTruthy();
  });
});
