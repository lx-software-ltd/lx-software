import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { FinanceDataLoadOrError, FinanceSaveStatus } from "../components/FinanceDataStatus";
import { FinanceInvestmentsPanel } from "../components/FinanceInvestmentsPanel";
import { FinancePensionPanel, FinanceSavingsPanel } from "../components/FinanceSavingsAndPensionPanels";
import { FinanceAccountsPanel } from "../components/FinanceAccountsPanel";
import { FinanceAllocationsPanel } from "../components/FinanceAllocationsPanel";
import { FinanceLiabilitiesPanel } from "../components/FinanceLiabilitiesPanel";
import { FinanceLedgerSheetPanel } from "../components/FinanceLedgerSheetPanel";
import { HouseStatementPanel } from "../components/HouseStatementPanel";
import { AdminTabList, type AdminTabItem } from "../components/ui";
import { useFinance } from "../hooks/useFinance";
import { adminTabButtonId } from "../lib/adminTabs";
import { isRowExpandedParam } from "../lib/expandedRecord";
import { HOUSE_DISPLAY_LABEL, LEDGER_RELATED_HOUSE_OPTIONS } from "../lib/houses";
import {
  EXPENSE_CATEGORIES,
  EXPENSE_LEDGER_FLAG_FIELDS,
  INCOME_CATEGORIES,
  INCOME_LEDGER_FLAG_FIELDS,
} from "../lib/financeModel";

type FinanceTab =
  | "hillmarton"
  | "morrison"
  | "investments"
  | "savings"
  | "pension"
  | "income"
  | "expenses"
  | "allocations"
  | "accounts"
  | "liabilities";

const FINANCE_TABS: readonly AdminTabItem<FinanceTab>[] = [
  { id: "hillmarton", label: HOUSE_DISPLAY_LABEL.hillmarton },
  { id: "morrison", label: HOUSE_DISPLAY_LABEL.morrison },
  { id: "investments", label: "Investments" },
  { id: "savings", label: "Savings" },
  { id: "pension", label: "Pension" },
  { id: "income", label: "Income" },
  { id: "expenses", label: "Expenses" },
  { id: "allocations", label: "Allocations" },
  { id: "accounts", label: "Accounts" },
  { id: "liabilities", label: "Liabilities" },
];

const TAB_ID_PREFIX = "finance";
const PANEL_ID = "finance-tabpanel";

const FINANCE_TAB_PARAM: Record<FinanceTab, string> = {
  hillmarton: "hillmarton-line",
  morrison: "morrison-line",
  investments: "investment",
  savings: "savings",
  pension: "pension",
  income: "income",
  expenses: "expenses",
  allocations: "allocation",
  accounts: "account",
  liabilities: "liability",
};

function financeTabFromSearch(search: string): FinanceTab {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const requested = params.get("tab");
  if (requested && FINANCE_TABS.some((item) => item.id === requested)) {
    return requested as FinanceTab;
  }
  for (const item of FINANCE_TABS) {
    if (params.get(FINANCE_TAB_PARAM[item.id])) return item.id;
  }
  return "accounts";
}

export function FinancePage() {
  const {
    data,
    patchHouse,
    patchLedgerRecords,
    patchInvestmentRecords,
    patchSavingsRecords,
    patchPensionRecords,
    patchAllocationRecords,
    patchAccountRecords,
    patchLiabilityRecords,
    patchExpenseIncomeAllocationPercents,
    isLoading,
    isError,
    isRefetching,
    refetch,
    isSaving,
    saveError,
    saveErrorDetail,
  } = useFinance();
  const location = useLocation();
  const navigate = useNavigate();
  const tab = financeTabFromSearch(location.search);
  const setTab = (id: FinanceTab) => {
    const params = new URLSearchParams(location.search);
    params.set("tab", id);
    for (const key of [...params.keys()]) {
      if (key !== FINANCE_TAB_PARAM[id] && isRowExpandedParam(key)) params.delete(key);
    }
    navigate({ pathname: location.pathname, search: params.toString() }, { replace: true });
  };
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    let changed = false;
    for (const key of [...params.keys()]) {
      if (key !== FINANCE_TAB_PARAM[tab] && isRowExpandedParam(key)) {
        params.delete(key);
        changed = true;
      }
    }
    if (changed) {
      navigate({ pathname: location.pathname, search: params.toString() }, { replace: true });
    }
  }, [location.pathname, location.search, navigate, tab]);

  return (
    <div>
      <FinanceDataLoadOrError
        isLoading={isLoading}
        isError={isError}
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
            tabs={FINANCE_TABS}
            active={tab}
            onChange={setTab}
            label="Finance sections"
            idPrefix={TAB_ID_PREFIX}
            panelId={PANEL_ID}
            disabled={isError}
          />

          {isError ? (
            <p className="text-muted small mb-0">
              Records could not be loaded, so editing is paused. Retry to continue.
            </p>
          ) : (
          <div
            className="tab-content"
            id={PANEL_ID}
            role="tabpanel"
            aria-labelledby={adminTabButtonId(TAB_ID_PREFIX, tab)}
          >
            {tab === "hillmarton" ? (
              <HouseStatementPanel
                houseKey="hillmarton"
                data={data.hillmarton}
                onPatch={(patch) => patchHouse("hillmarton", patch)}
                isSaving={isSaving}
              />
            ) : null}
            {tab === "morrison" ? (
              <HouseStatementPanel
                houseKey="morrison"
                data={data.morrison}
                onPatch={(patch) => patchHouse("morrison", patch)}
                isSaving={isSaving}
              />
            ) : null}
            {tab === "investments" ? (
              <FinanceInvestmentsPanel
                records={data.investmentRecords}
                onPatch={patchInvestmentRecords}
                isSaving={isSaving}
                relatedHouseOptions={LEDGER_RELATED_HOUSE_OPTIONS}
              />
            ) : null}
            {tab === "savings" ? (
              <FinanceSavingsPanel records={data.savingsRecords} onPatch={patchSavingsRecords} isSaving={isSaving} />
            ) : null}
            {tab === "pension" ? (
              <FinancePensionPanel
                records={data.pensionRecords}
                onPatch={patchPensionRecords}
                allocationRecords={data.allocationRecords}
                isSaving={isSaving}
              />
            ) : null}
            {tab === "income" ? (
              <FinanceLedgerSheetPanel
                sheetId="income"
                categories={INCOME_CATEGORIES}
                records={data.incomeRecords}
                onPatch={(patch) => patchLedgerRecords("income", patch)}
                isSaving={isSaving}
                formSectionTitle="Income record"
                tableSectionTitle="Monthly Income"
                deleteConfirmMessage="Delete this income record?"
                emptyMessage="No income records yet."
                relatedHouseOptions={LEDGER_RELATED_HOUSE_OPTIONS}
                incomeFlagFields={INCOME_LEDGER_FLAG_FIELDS}
                allocationRecordsForSyntheticIncome={data.allocationRecords}
              />
            ) : null}
            {tab === "expenses" ? (
              <FinanceLedgerSheetPanel
                sheetId="expenses"
                categories={EXPENSE_CATEGORIES}
                records={data.expenseRecords}
                onPatch={(patch) => patchLedgerRecords("expenses", patch)}
                isSaving={isSaving}
                formSectionTitle="Expense record"
                tableSectionTitle="Monthly Expenses"
                deleteConfirmMessage="Delete this expense record?"
                emptyMessage="No expense records yet."
                alphabetizeCategoryDropdown
                relatedHouseOptions={LEDGER_RELATED_HOUSE_OPTIONS}
                expenseIncomeAllocationPercents={data.expenseIncomeAllocationPercents}
                onPatchExpenseIncomeAllocationPercents={patchExpenseIncomeAllocationPercents}
                incomeRecordsForDerivedExpenses={data.incomeRecords}
                expenseFlagFields={EXPENSE_LEDGER_FLAG_FIELDS}
              />
            ) : null}
            {tab === "allocations" ? (
              <FinanceAllocationsPanel
                records={data.allocationRecords}
                onPatch={patchAllocationRecords}
                isSaving={isSaving}
              />
            ) : null}
            {tab === "accounts" ? (
              <FinanceAccountsPanel records={data.accountRecords} onPatch={patchAccountRecords} isSaving={isSaving} />
            ) : null}
            {tab === "liabilities" ? (
              <FinanceLiabilitiesPanel
                records={data.liabilityRecords}
                onPatch={patchLiabilityRecords}
                isSaving={isSaving}
                relatedHouseOptions={LEDGER_RELATED_HOUSE_OPTIONS}
              />
            ) : null}
          </div>
          )}
        </>
      ) : null}
    </div>
  );
}
