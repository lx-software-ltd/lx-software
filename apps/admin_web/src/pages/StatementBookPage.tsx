import { useState, type ReactNode } from "react";
import { FinanceDataLoadOrError, FinanceSaveStatus } from "../components/FinanceDataStatus";
import { HouseStatementPanel } from "../components/HouseStatementPanel";
import { StatementBookDashboardCard } from "../components/StatementBookDashboardCard";
import { ExecutiveBoardTab } from "../components/board/ExecutiveBoardTab";
import { AdminPageIntro, AdminTabList, type AdminTabItem } from "../components/ui";
import { useStatementBook } from "../hooks/useStatementBook";
import { adminTabButtonId } from "../lib/adminTabs";
import { defaultFiscalYearIdForNowUtc, type FiscalYearId } from "../lib/fiscalYearFinance";
import { SIU_TIN_DEI_BOOK_KEY, STATEMENT_BOOK_DISPLAY_LABEL } from "../lib/statementOwners";
import type { StatementBookKey } from "../lib/financeTypes";

type StatementBookTab = "dashboard" | "expenses" | "gains" | "board";

const STATEMENT_BOOK_TABS: readonly AdminTabItem<StatementBookTab>[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "expenses", label: "Expenses" },
  { id: "gains", label: "Gains" },
];

const EXECUTIVE_BOARD_TAB: AdminTabItem<StatementBookTab> = {
  id: "board",
  label: "Executive Board",
};

export function StatementBookPage({
  bookKey,
  dashboardExtra,
}: {
  readonly bookKey: StatementBookKey;
  readonly dashboardExtra?: ReactNode;
}) {
  const title = STATEMENT_BOOK_DISPLAY_LABEL[bookKey];
  const hasExecutiveBoard = bookKey === SIU_TIN_DEI_BOOK_KEY;
  const tabs = hasExecutiveBoard
    ? [...STATEMENT_BOOK_TABS, EXECUTIVE_BOARD_TAB]
    : STATEMENT_BOOK_TABS;
  const {
    data,
    patchBook,
    isLoading,
    isError,
    isRefetching,
    refetch,
    isSaving,
    saveError,
    saveErrorDetail,
  } = useStatementBook(bookKey);
  const [tab, setTab] = useState<StatementBookTab>("dashboard");
  const [fiscalYear, setFiscalYear] = useState<FiscalYearId>(() =>
    defaultFiscalYearIdForNowUtc(),
  );
  const idPrefix = `book-${bookKey}`;
  const panelId = `${idPrefix}-tabpanel`;
  // The board has its own API; it stays usable even when the book failed to load.
  const canShowTab = !isError || tab === "board";

  return (
    <div>
      <h1 className="h3 mb-3">{title}</h1>
      <AdminPageIntro>
        Record invoices and receipts for {title}. Upload a PDF or image to
        extract lines, or add a row by hand. Expenses and gains are stored
        separately; imports on each tab keep only that tab&apos;s line type.
        Default currency is HKD.
      </AdminPageIntro>
      <FinanceDataLoadOrError
        isLoading={isLoading}
        isError={isError}
        loadErrorMessage={`Could not load ${title} records. Check API configuration and sign-in.`}
        onRetry={() => void refetch()}
        isRetrying={isRefetching}
      />
      {!isLoading ? (
        <>
          <FinanceSaveStatus
            isSaving={isSaving}
            saveError={saveError}
            saveErrorDetail={saveErrorDetail}
          />

          <AdminTabList
            tabs={tabs}
            active={tab}
            onChange={setTab}
            label={`${title} sections`}
            idPrefix={idPrefix}
            panelId={panelId}
          />

          {!canShowTab ? (
            <p className="text-muted small mb-0">
              Records could not be loaded, so editing is paused. Retry to continue.
            </p>
          ) : (
          <div
            className="tab-content"
            id={panelId}
            role="tabpanel"
            aria-labelledby={adminTabButtonId(idPrefix, tab)}
          >
            {tab === "dashboard" ? (
              <>
                <StatementBookDashboardCard
                  title={title}
                  data={data}
                  fiscalYear={fiscalYear}
                  onFiscalYearChange={setFiscalYear}
                />
                {dashboardExtra ? <div className="mt-3">{dashboardExtra}</div> : null}
              </>
            ) : null}
            {tab === "expenses" ? (
              <HouseStatementPanel
                houseKey={bookKey}
                data={data}
                onPatch={patchBook}
                lockedLineType="expenditure"
                showHouseDetails={false}
                showMortgageImport={false}
                importTitle="Import invoice (PDF)"
                importDescription="Upload an invoice PDF or image. The file is stored under Assets and OpenRouter extracts expense lines only."
                importFileLabel="Invoice file"
                lineSectionTitle="Expense"
                tableSectionTitle="Expenses"
                emptyMessage="No expenses yet."
              />
            ) : null}
            {tab === "gains" ? (
              <HouseStatementPanel
                houseKey={bookKey}
                data={data}
                onPatch={patchBook}
                lockedLineType="income"
                showHouseDetails={false}
                showMortgageImport={false}
                importTitle="Import invoice (PDF)"
                importDescription="Upload a receipt or invoice PDF or image. The file is stored under Assets and OpenRouter extracts gain lines only."
                importFileLabel="Invoice file"
                lineSectionTitle="Gain"
                tableSectionTitle="Gains"
                emptyMessage="No gains yet."
              />
            ) : null}
            {tab === "board" && hasExecutiveBoard ? <ExecutiveBoardTab /> : null}
          </div>
          )}
        </>
      ) : null}
    </div>
  );
}
