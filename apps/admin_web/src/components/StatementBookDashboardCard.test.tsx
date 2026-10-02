import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { adminFetch } from "../lib/apiAdminClient";
import { GLOBAL_DEFAULT_CURRENCY } from "../lib/currencies";
import { formatMoneyAmount } from "../lib/formatDisplay";
import { netGainsMinusExpensesInBase } from "../lib/frankfurterRates";
import { defaultFiscalYearIdForNowUtc } from "../lib/fiscalYearFinance";
import { lxSoftwareBookFixture, siuTinDeiBookFixture } from "../lib/mock/fixtures";
import { StatementBookDashboardCard } from "./StatementBookDashboardCard";

vi.mock("../lib/apiAdminClient", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/apiAdminClient")>();
  return { ...actual, adminFetch: vi.fn() };
});

function renderCard(
  data: typeof siuTinDeiBookFixture,
  title: string,
): ReturnType<typeof render> {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree: ReactElement = (
    <QueryClientProvider client={client}>
      <StatementBookDashboardCard
        title={title}
        data={data}
        fiscalYear={defaultFiscalYearIdForNowUtc()}
        onFiscalYearChange={() => undefined}
      />
    </QueryClientProvider>
  );
  return render(tree);
}

describe("StatementBookDashboardCard net", () => {
  beforeEach(() => {
    vi.mocked(adminFetch).mockReset();
  });

  it("shows one HKD net when every line is already HKD", () => {
    renderCard(lxSoftwareBookFixture, "LX Software");
    expect(screen.getByText(formatMoneyAmount(44200, GLOBAL_DEFAULT_CURRENCY))).toBeTruthy();
    expect(screen.queryByText(/US\$|\bUSD\b/)).toBeNull();
  });

  it("converts mixed-currency gains and expenses to one HKD net", async () => {
    const usdRate = 0.12754;
    vi.mocked(adminFetch).mockResolvedValue(
      new Response(
        JSON.stringify([{ quote: "USD", rate: usdRate, date: "2026-10-01", base: "HKD" }]),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    renderCard(siuTinDeiBookFixture, "Siu Tin Dei");
    const expected = netGainsMinusExpensesInBase(
      { HKD: 1200 },
      { USD: 411.4 },
      GLOBAL_DEFAULT_CURRENCY,
      new Map([["USD", usdRate]]),
    );
    await waitFor(() => {
      expect(screen.getByText(formatMoneyAmount(expected, GLOBAL_DEFAULT_CURRENCY))).toBeTruthy();
    });
    expect(screen.getByText(formatMoneyAmount(1200, "HKD"))).toBeTruthy();
    expect(screen.getByText(formatMoneyAmount(411.4, "USD"))).toBeTruthy();
    expect(screen.getByText(/Frankfurter/)).toBeTruthy();
  });
});
