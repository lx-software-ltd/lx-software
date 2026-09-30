import { useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { FinanceDataLoadOrError } from "../components/FinanceDataStatus";
import { AdminKpi, AdminKpiAmounts } from "../components/ui";
import { StatementBookDashboardCard } from "../components/StatementBookDashboardCard";
import { AllocationCoverageDashboardCard } from "../components/dashboard/AllocationCoverageDashboardCard";
import { DashboardApiHealthCard } from "../components/dashboard/DashboardApiHealthCard";
import { DashboardSessionCard } from "../components/dashboard/DashboardSessionCard";
import { HouseSummaryCard } from "../components/dashboard/HouseSummaryCard";
import { MonthlyViewExpenseAllocationsSection } from "../components/dashboard/MonthlyViewExpenseAllocationsSection";
import { AvailableBalanceDashboardCard } from "../components/dashboard/AvailableBalanceDashboardCard";
import { PensionDashboardCard } from "../components/dashboard/PensionDashboardCard";
import { adminFetchJson } from "../lib/apiAdminClient";
import { useFinance } from "../hooks/useFinance";
import { EMPTY_STATEMENT_BOOK, statementBookQuery } from "../hooks/useStatementBook";
import { formatNonZeroMoneyLines } from "../lib/formatDisplay";
import {
  defaultFiscalYearIdForNowUtc,
  fiscalYearIdToStartCalendarYear,
  netGainsMinusExpensesByCurrency,
  sumHouseStatementLinesForFiscalYear,
  type FiscalYearId,
} from "../lib/fiscalYearFinance";
import { monthlyLedgerNetByCurrency, sumMonthlyFinanceLedgerAmountsByHouse } from "../lib/financeModel";
import { HOUSE_DISPLAY_LABEL } from "../lib/houses";
import {
  STATEMENT_BOOK_DASHBOARD_ORDER,
  STATEMENT_BOOK_DISPLAY_LABEL,
} from "../lib/statementOwners";

function bookNet(
  lines: Parameters<typeof sumHouseStatementLinesForFiscalYear>[0],
  year: number,
): readonly string[] {
  const sums = sumHouseStatementLinesForFiscalYear(lines, year);
  return formatNonZeroMoneyLines(
    netGainsMinusExpensesByCurrency(sums.incomeByCurrency, sums.expensesByCurrency),
  );
}

export function DashboardPage() {
  const healthQuery = useQuery({
    queryKey: ["admin", "health"],
    queryFn: () =>
      adminFetchJson<{ status?: string }>("/health", { requireAuth: false }),
  });

  const meQuery = useQuery({
    queryKey: ["admin", "me"],
    queryFn: () =>
      adminFetchJson<{ sub?: string; email?: string }>("/me"),
  });
  const [bookFiscalYear, setBookFiscalYear] = useState<Partial<Record<string, FiscalYearId>>>({});
  const [hillmartonFy, setHillmartonFy] = useState<FiscalYearId>(() =>
    defaultFiscalYearIdForNowUtc(),
  );
  const [morrisonFy, setMorrisonFy] = useState<FiscalYearId>(() =>
    defaultFiscalYearIdForNowUtc(),
  );

  const bookQueries = useQueries({
    queries: STATEMENT_BOOK_DASHBOARD_ORDER.map((bookKey) => statementBookQuery(bookKey)),
  });
  const booksLoading = bookQueries.some((query) => query.isLoading);
  const booksError = bookQueries.some((query) => query.isError);
  const booksRetrying = bookQueries.some((query) => query.isRefetching);

  const financeQuery = useFinance();
  const fiscalYearStart = fiscalYearIdToStartCalendarYear(defaultFiscalYearIdForNowUtc());
  const kpis = useMemo(() => {
    const finance = financeQuery.data;
    if (!finance || bookQueries.some((query) => !query.data)) return null;
    const houseNet = (houseKey: "hillmarton" | "morrison") => {
      const monthly = sumMonthlyFinanceLedgerAmountsByHouse(
        finance.incomeRecords,
        finance.expenseRecords,
        houseKey,
        finance.expenseIncomeAllocationPercents,
        finance.allocationRecords,
      );
      return formatNonZeroMoneyLines(monthlyLedgerNetByCurrency(monthly));
    };
    return {
      books: STATEMENT_BOOK_DASHBOARD_ORDER.map((bookKey, index) => ({
        bookKey,
        label: STATEMENT_BOOK_DISPLAY_LABEL[bookKey],
        lines: bookNet(bookQueries[index]?.data?.lines ?? [], fiscalYearStart),
      })),
      hillmarton: houseNet("hillmarton"),
      morrison: houseNet("morrison"),
    };
  }, [bookQueries, financeQuery.data, fiscalYearStart]);

  return (
    <div className="admin-dashboard">
      {kpis ? (
        <div className="admin-kpi-row">
          {kpis.books.map((book) => (
            <AdminKpi
              key={book.bookKey}
              label={`${book.label} net`}
              value={<AdminKpiAmounts lines={book.lines} />}
              hint="This fiscal year"
            />
          ))}
          <AdminKpi label="Hillmarton" value={<AdminKpiAmounts lines={kpis.hillmarton} />} hint="Monthly net" />
          <AdminKpi label="The Morrison" value={<AdminKpiAmounts lines={kpis.morrison} />} hint="Monthly net" />
        </div>
      ) : null}

      <FinanceDataLoadOrError
        isLoading={booksLoading}
        isError={booksError}
        loadingMessage="Loading statement book summaries…"
        loadErrorMessage="Could not load statement book summaries. Check API configuration and sign-in."
        onRetry={() => {
          for (const query of bookQueries) void query.refetch();
        }}
        isRetrying={booksRetrying}
      />
      {!booksLoading && !booksError ? (
        <div className="row g-3 mb-3">
          {STATEMENT_BOOK_DASHBOARD_ORDER.map((bookKey, index) => (
            <div className="col-md-6 col-xl-4" key={bookKey}>
              <StatementBookDashboardCard
                title={STATEMENT_BOOK_DISPLAY_LABEL[bookKey]}
                data={bookQueries[index]?.data ?? EMPTY_STATEMENT_BOOK}
                fiscalYear={bookFiscalYear[bookKey] ?? defaultFiscalYearIdForNowUtc()}
                onFiscalYearChange={(fiscalYear) =>
                  setBookFiscalYear((current) => ({ ...current, [bookKey]: fiscalYear }))
                }
              />
            </div>
          ))}
        </div>
      ) : null}

      <FinanceDataLoadOrError
        isLoading={financeQuery.isLoading}
        isError={financeQuery.isError}
        loadErrorMessage="Could not load finance data for summaries. Check API configuration and sign-in."
        onRetry={() => void financeQuery.refetch()}
        isRetrying={financeQuery.isRefetching}
      />
      {!financeQuery.isLoading && !financeQuery.isError ? (
        <>
          <div className="row g-3 mb-3">
            <div className="col-md-6">
              <HouseSummaryCard
                houseName={HOUSE_DISPLAY_LABEL.hillmarton}
                houseKey="hillmarton"
                fiscalYear={hillmartonFy}
                onFiscalYearChange={setHillmartonFy}
              />
            </div>
            <div className="col-md-6">
              <HouseSummaryCard
                houseName={HOUSE_DISPLAY_LABEL.morrison}
                houseKey="morrison"
                fiscalYear={morrisonFy}
                onFiscalYearChange={setMorrisonFy}
              />
            </div>
          </div>
          <MonthlyViewExpenseAllocationsSection />
          <div className="row g-3 mb-4">
            <div className="col-12 col-lg-6 d-flex flex-column gap-3">
              <PensionDashboardCard />
              <AvailableBalanceDashboardCard />
            </div>
            <div className="col-12 col-lg-6">
              <AllocationCoverageDashboardCard />
            </div>
          </div>
        </>
      ) : null}

      <div className="row g-3">
        <div className="col-md-6">
          <DashboardApiHealthCard
            isLoading={healthQuery.isLoading}
            isError={healthQuery.isError}
            status={healthQuery.data?.status}
          />
        </div>
        <div className="col-md-6">
          <DashboardSessionCard
            isLoading={meQuery.isLoading}
            isError={meQuery.isError}
            sub={meQuery.data?.sub}
            email={meQuery.data?.email}
          />
        </div>
      </div>
    </div>
  );
}
