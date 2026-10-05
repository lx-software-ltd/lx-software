import { useEffect, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { FinanceDataLoadOrError, FinanceSaveStatus } from "../components/FinanceDataStatus";
import { HouseStatementPanel } from "../components/HouseStatementPanel";
import { MirroredBookSummaryCard } from "../components/MirroredBookSummaryCard";
import { StatementBookDashboardCard } from "../components/StatementBookDashboardCard";
import { ExecutiveBoardTab } from "../components/board/ExecutiveBoardTab";
import { LinkedInTab } from "../components/linkedin/LinkedInTab";
import { AdminTabList, type AdminTabItem } from "../components/ui";
import { useStatementBook } from "../hooks/useStatementBook";
import { adminTabButtonId } from "../lib/adminTabs";
import { isRowExpandedParam } from "../lib/expandedRecord";
import { defaultFiscalYearIdForNowUtc, type FiscalYearId } from "../lib/fiscalYearFinance";
import { defaultStatementBookTab, type StatementBookTab } from "../lib/statementBookTabs";
import {
  LX_SOFTWARE_BOOK_KEY,
  SIU_TIN_DEI_BOOK_KEY,
  STATEMENT_BOOK_DISPLAY_LABEL,
  isMirroredStatementBook,
} from "../lib/statementOwners";
import type { StatementBookKey } from "../lib/financeTypes";

const STATEMENT_BOOK_TABS: readonly AdminTabItem<StatementBookTab>[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "expenses", label: "Expenses" },
  { id: "gains", label: "Gains" },
];

const EXECUTIVE_BOARD_TAB: AdminTabItem<StatementBookTab> = {
  id: "board",
  label: "Executive Board",
};

const LINKEDIN_TAB: AdminTabItem<StatementBookTab> = {
  id: "linkedin",
  label: "LinkedIn",
};

function rowParamForTab(tab: StatementBookTab, bookKey: string, search: string): string | null {
  if (tab === "expenses" || tab === "gains") return `${bookKey}-line`;
  if (tab !== "linkedin") return null;
  const section = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search).get("section");
  if (section === "ideas") return "linkedin-idea";
  if (section === "calendar" || section === "published" || section === "settings") return null;
  return "linkedin-post";
}

export function StatementBookPage({
  bookKey,
  dashboardExtra,
}: {
  readonly bookKey: StatementBookKey;
  readonly dashboardExtra?: ReactNode;
}) {
  const title = STATEMENT_BOOK_DISPLAY_LABEL[bookKey];
  const readOnly = isMirroredStatementBook(bookKey);
  const hasExecutiveBoard = bookKey === SIU_TIN_DEI_BOOK_KEY;
  const hasLinkedIn = bookKey === LX_SOFTWARE_BOOK_KEY;
  const tabs = [
    ...STATEMENT_BOOK_TABS,
    ...(hasExecutiveBoard ? [EXECUTIVE_BOARD_TAB] : []),
    ...(hasLinkedIn ? [LINKEDIN_TAB] : []),
  ];
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
  const location = useLocation();
  const navigate = useNavigate();
  const tab = defaultStatementBookTab(hasExecutiveBoard, location.search, { linkedIn: hasLinkedIn });
  const setTab = (id: StatementBookTab) => {
    const params = new URLSearchParams(location.search);
    params.set("tab", id);
    const keep = rowParamForTab(id, bookKey, params.toString());
    for (const key of [...params.keys()]) {
      if (key !== keep && isRowExpandedParam(key)) params.delete(key);
    }
    if (id !== "board" && id !== "linkedin") params.delete("section");
    navigate({ pathname: location.pathname, search: params.toString() }, { replace: true });
  };
  const [fiscalYear, setFiscalYear] = useState<FiscalYearId>(() =>
    defaultFiscalYearIdForNowUtc(),
  );
  useEffect(() => {
    if (tab === "board") return;
    const params = new URLSearchParams(location.search);
    const keep = rowParamForTab(tab, bookKey, location.search);
    let changed = false;
    for (const key of [...params.keys()]) {
      if (key !== keep && isRowExpandedParam(key)) {
        params.delete(key);
        changed = true;
      }
    }
    if (changed) {
      navigate({ pathname: location.pathname, search: params.toString() }, { replace: true });
    }
  }, [bookKey, location.pathname, location.search, navigate, tab]);
  const idPrefix = `book-${bookKey}`;
  const panelId = `${idPrefix}-tabpanel`;
  // The board has its own API; it stays usable even when the book failed to load.
  const canShowTab = !isError || tab === "board" || tab === "linkedin";

  return (
    <div>
      <FinanceDataLoadOrError
        isLoading={isLoading}
        isError={isError}
        loadErrorMessage={`Could not load ${title} records. Check API configuration and sign-in.`}
        onRetry={() => void refetch()}
        isRetrying={isRefetching}
      />
      {!isLoading ? (
        <>
          {readOnly ? null : (
            <FinanceSaveStatus
              isSaving={isSaving}
              saveError={saveError}
              saveErrorDetail={saveErrorDetail}
            />
          )}

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
                  showTitle={bookKey !== LX_SOFTWARE_BOOK_KEY}
                  data={data}
                  fiscalYear={fiscalYear}
                  onFiscalYearChange={setFiscalYear}
                />
                {readOnly ? (
                  <div className="mt-3">
                    <MirroredBookSummaryCard bookKey={bookKey} />
                  </div>
                ) : null}
                {dashboardExtra ? <div className="mt-3">{dashboardExtra}</div> : null}
              </>
            ) : null}
            {tab === "expenses" ? (
              <HouseStatementPanel
                houseKey={bookKey}
                data={data}
                onPatch={patchBook}
                isSaving={isSaving}
                readOnly={readOnly}
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
                isSaving={isSaving}
                readOnly={readOnly}
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
            {tab === "linkedin" && hasLinkedIn ? <LinkedInTab /> : null}
          </div>
          )}
        </>
      ) : null}
    </div>
  );
}
