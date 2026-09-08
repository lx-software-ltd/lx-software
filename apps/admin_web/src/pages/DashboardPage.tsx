import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FinanceDataLoadOrError } from "../components/FinanceDataStatus";
import { AdminPageIntro } from "../components/ui";
import { StatementBookDashboardCard } from "../components/StatementBookDashboardCard";
import { AllocationCoverageDashboardCard } from "../components/dashboard/AllocationCoverageDashboardCard";
import { DashboardApiHealthCard } from "../components/dashboard/DashboardApiHealthCard";
import { OpenRouterUsageCard } from "../components/dashboard/OpenRouterUsageCard";
import { useOpenRouterUsage } from "../hooks/useOpenRouterUsage";
import { DashboardSessionCard } from "../components/dashboard/DashboardSessionCard";
import { HouseSummaryCard } from "../components/dashboard/HouseSummaryCard";
import { MonthlyViewExpenseAllocationsSection } from "../components/dashboard/MonthlyViewExpenseAllocationsSection";
import { AvailableBalanceDashboardCard } from "../components/dashboard/AvailableBalanceDashboardCard";
import { PensionDashboardCard } from "../components/dashboard/PensionDashboardCard";
import { adminFetchJson } from "../lib/apiAdminClient";
import { useFinance } from "../hooks/useFinance";
import { useStatementBook } from "../hooks/useStatementBook";
import { defaultFiscalYearIdForNowUtc, type FiscalYearId } from "../lib/fiscalYearFinance";
import { HOUSE_DISPLAY_LABEL } from "../lib/houses";
import {
  LX_SOFTWARE_BOOK_KEY,
  SIU_TIN_DEI_BOOK_KEY,
  STATEMENT_BOOK_DISPLAY_LABEL,
} from "../lib/statementOwners";

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
  const openrouterQuery = useOpenRouterUsage();

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

  return (
    <div>
      <h1 className="h3 mb-3">Dashboard</h1>
      <AdminPageIntro>
        Welcome to the LX Software admin console. Use the navigation menu to
        manage assets and records.
      </AdminPageIntro>

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

      <div className="row g-3 mb-3">
        <div className="col-12">
          <OpenRouterUsageCard
            isLoading={openrouterQuery.isLoading}
            isError={openrouterQuery.isError}
            data={openrouterQuery.data}
          />
        </div>
      </div>

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
