import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { formatMoneyAmountWithoutCurrency } from "../lib/formatDisplay";
import { financeFixture } from "../lib/mock/fixtures";
import { HouseStatementPanel } from "./HouseStatementPanel";

function renderPanel(houseKey: "hillmarton" | "morrison"): ReturnType<typeof render> {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree: ReactElement = (
    <QueryClientProvider client={client}>
      <HouseStatementPanel
        houseKey={houseKey}
        data={financeFixture[houseKey]}
        onPatch={vi.fn()}
      />
    </QueryClientProvider>
  );
  return render(tree);
}

describe("HouseStatementPanel columns", () => {
  it("shows Gross as currency plus amount and omits Net, VAT, and Currency", () => {
    renderPanel("hillmarton");

    expect(screen.getByRole("columnheader", { name: "Gross" })).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: "Net" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "VAT" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Currency" })).toBeNull();

    const rent = financeFixture.hillmarton.lines.find((line) => line.id === "hl-1");
    expect(rent).toBeDefined();
    const expected = `${rent!.currency} ${formatMoneyAmountWithoutCurrency(rent!.grossAmount, rent!.currency)}`;
    expect(screen.getAllByText(expected).length).toBeGreaterThan(0);
  });

  it("formats Morrison gross the same way", () => {
    renderPanel("morrison");

    const fee = financeFixture.morrison.lines[0];
    expect(fee).toBeDefined();
    const expected = `${fee!.currency} ${formatMoneyAmountWithoutCurrency(fee!.grossAmount, fee!.currency)}`;
    expect(screen.getAllByText(expected).length).toBeGreaterThan(0);
    expect(screen.queryByRole("columnheader", { name: "Net" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "VAT" })).toBeNull();
  });
});
