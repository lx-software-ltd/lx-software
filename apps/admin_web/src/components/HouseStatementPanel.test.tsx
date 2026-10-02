import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { formatMoneyAmount } from "../lib/formatDisplay";
import { financeFixture } from "../lib/mock/fixtures";
import { HouseStatementPanel } from "./HouseStatementPanel";

function renderPanel(houseKey: "hillmarton" | "morrison"): ReturnType<typeof render> {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree: ReactElement = (
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <HouseStatementPanel
          houseKey={houseKey}
          data={financeFixture[houseKey]}
          onPatch={vi.fn()}
        />
      </QueryClientProvider>
    </MemoryRouter>
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
    expectGrossCell(rent!.currency, rent!.grossAmount);
  });

  it("formats Morrison gross the same way", () => {
    renderPanel("morrison");

    const fee = financeFixture.morrison.lines[0];
    expect(fee).toBeDefined();
    expectGrossCell(fee!.currency, fee!.grossAmount);
    expect(screen.queryByRole("columnheader", { name: "Net" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "VAT" })).toBeNull();
  });
});

function expectGrossCell(currency: string, amount: number): void {
  const expected = formatMoneyAmount(amount, currency);
  const cells = screen
    .getAllByRole("cell")
    .filter((cell) => cell.getAttribute("data-column") === "gross");
  expect(cells.some((cell) => cell.textContent?.replace(/\s+/g, " ").trim() === expected)).toBe(
    true,
  );
}
