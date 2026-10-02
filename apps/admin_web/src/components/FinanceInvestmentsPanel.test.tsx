import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { financeFixture } from "../lib/mock/fixtures";
import { LEDGER_RELATED_HOUSE_OPTIONS } from "../lib/houses";
import { FinanceInvestmentsPanel } from "./FinanceInvestmentsPanel";

function renderPanel(): ReturnType<typeof render> {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree: ReactElement = (
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <FinanceInvestmentsPanel
          records={financeFixture.investmentRecords}
          onPatch={vi.fn()}
          relatedHouseOptions={LEDGER_RELATED_HOUSE_OPTIONS}
        />
      </QueryClientProvider>
    </MemoryRouter>
  );
  return render(tree);
}

describe("FinanceInvestmentsPanel columns", () => {
  it("labels the principal column Principal and puts a currency converter on that total", () => {
    renderPanel();

    expect(screen.getByRole("columnheader", { name: /Principal/ })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /Current Value/ })).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: /Sort by Currency/ })).toBeNull();

    expect(screen.getByLabelText("Principal total display currency")).toBeTruthy();
    expect(screen.getByLabelText("Current value total display currency")).toBeTruthy();
  });
});
