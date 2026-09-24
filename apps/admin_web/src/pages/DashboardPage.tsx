import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FinanceDataLoadOrError } from "../components/FinanceDataStatus";
import { AdminKpi, AdminPageHeader } from "../components/ui";
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
import { useStatementBook } from "../hooks/useStatementBook";
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
  LX_SOFTWARE_BOOK_KEY,
  SIU_TIN_DEI_BOOK_KEY,
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

function MoneyStack({ lines }: { readonly lines: readonly string[] }) {
  return (
    <span className="admin-kpi-amounts">
      {lines.map((line, index) => (
        <span key={`${line}-${index}`} className="admin-kpi-amount">
          {line}
        </span>
      ))}
    </span>
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
  const [lxSoftwareFy, setLxSoftwareFy] = useState<FiscalYearId>(() =>
    defaultFiscalYearIdForNowUtc(),
  );
  const [siuTinDeiFy, setSiuTinDeiFy] = useState<FiscalYearId>(() =>
    defaultFiscalYearIdForNowUtc(),
  );
  const [hillmartonFy, setHillmartonFy] = useState<FiscalYearId>(() =>
    defaultFiscalYearIdForNowUtc(),
  );
  const [morrisonFy, setMorrisonFy] = useState<FiscalYearId>(() =>
    defaultFiscalYearIdForNowUtc(),
  );

  const lxSoftwareQuery = useStatementBook(LX_SOFTWARE_BOOK_KEY);
  const siuTinDeiQuery = useStatementBook(SIU_TIN_DEI_BOOK_KEY);
  const booksLoading = lxSoftwareQuery.isLoading || siuTinDeiQuery.isLoading;
  const booksError = lxSoftwareQuery.isError || siuTinDeiQuery.isError;

  const financeQuery = useFinance();
  const fiscalYearStart = fiscalYearIdToStartCalendarYear(defaultFiscalYearIdForNowUtc());
  const kpis = useMemo(() => {
    const finance = financeQuery.data;
    const lx = lxSoftwareQuery.data;
    const siu = siuTinDeiQuery.data;
    if (!finance || !lx || !siu) return null;
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
      lx: bookNet(lx.lines, fiscalYearStart),
      siu: bookNet(siu.lines, fiscalYearStart),
      hillmarton: houseNet("hillmarton"),
      morrison: houseNet("morrison"),
    };
  }, [financeQuery.data, fiscalYearStart, lxSoftwareQuery.data, siuTinDeiQuery.data]);

  return (
    <div>
      <AdminPageHeader
        title="Dashboard"
        help="Balances, statement books, and house summaries for the current fiscal year."
      />
      {kpis ? (
        <div className="admin-kpi-row">
          <AdminKpi label="LX Software net" value={<MoneyStack lines={kpis.lx} />} hint="This fiscal year" />
          <AdminKpi label="Siu Tin Dei net" value={<MoneyStack lines={kpis.siu} />} hint="This fiscal year" />
          <AdminKpi label="Hillmarton" value={<MoneyStack lines={kpis.hillmarton} />} hint="Monthly net" />
          <AdminKpi label="The Morrison" value={<MoneyStack lines={kpis.morrison} />} hint="Monthly net" />
        </div>
      ) : null}

      <FinanceDataLoadOrError
        isLoading={booksLoading}
        isError={booksError}
        loadingMessage="Loading LX Software and Siu Tin Dei summaries…"
        loadErrorMessage="Could not load LX Software and Siu Tin Dei summaries. Check API configuration and sign-in."
        onRetry={() => {
          void lxSoftwareQuery.refetch();
          void siuTinDeiQuery.refetch();
        }}
        isRetrying={lxSoftwareQuery.isRefetching || siuTinDeiQuery.isRefetching}
      />
      {!booksLoading && !booksError ? (
        <div className="row g-3 mb-3">
          <div className="col-md-6">
            <StatementBookDashboardCard
              title={STATEMENT_BOOK_DISPLAY_LABEL.lxSoftware}
              data={lxSoftwareQuery.data}
              fiscalYear={lxSoftwareFy}
              onFiscalYearChange={setLxSoftwareFy}
            />
          </div>
          <div className="col-md-6">
            <StatementBookDashboardCard
              title={STATEMENT_BOOK_DISPLAY_LABEL.siuTinDei}
              data={siuTinDeiQuery.data}
              fiscalYear={siuTinDeiFy}
              onFiscalYearChange={setSiuTinDeiFy}
            />
          </div>
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

      <DashboardApiHealthCard
        isLoading={healthQuery.isLoading}
        isError={healthQuery.isError}
        status={healthQuery.data?.status}
      />
      <DashboardSessionCard
        isLoading={meQuery.isLoading}
        isError={meQuery.isError}
        sub={meQuery.data?.sub}
        email={meQuery.data?.email}
      />
    </div>
  );
}
