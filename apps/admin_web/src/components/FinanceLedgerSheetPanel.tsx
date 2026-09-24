import { type FormEvent, useCallback, useMemo, useState } from "react";
import {
  coerceSupportedCurrency,
  GLOBAL_DEFAULT_CURRENCY,
  type CurrencyCode,
} from "../lib/currencies";
import { convertAmountToBase } from "../lib/frankfurterRates";
import { parseAmount } from "../lib/formParse";
import {
  buildDerivedExpenseLedgerRowsFromTaggedIncome,
  ledgerMonthlyAmount,
  newStatementLineId,
  type ExpenseIncomeAllocationPercents,
  type ExpenseLedgerFlagField,
  type FinanceAllocationRecord,
  type FinanceLedgerAmountPeriod,
  type FinanceLedgerRecord,
  type HouseKey,
  type IncomeLedgerFlagField,
  syntheticIncomeLedgerRowsFromAllocations,
} from "../lib/financeModel";
import { DRAFT_RECORD_ID } from "../lib/expandedRecord";
import { useExpandedRecord } from "../hooks/useExpandedRecord";
import { useHydrateExpandedRecord } from "../hooks/useHydrateExpandedRecord";
import { useFrankfurterRatesForTotals } from "../hooks/useFrankfurterRatesForTotals";
import {
  AdminCell,
  AdminDataTable,
  AdminDataTableCellMeta,
  AdminDataTableEmptyRow,
  type AdminDataTableColumn,
  AdminCreateButton,
  AdminEditorPanel,
  AdminExpandableRow,
  AdminFilterBar,
  AdminFilterField,
  AdminRecordTable,
  AdminRowActions,
  ConfirmDialog,
  AdminEditorSection,
  AdminTableTotalCurrency,
  AdminTableTotalLabel,
  CurrencySelect,
  MoneyAmount,
  TableSortHeaderButton,
} from "./ui";

type LedgerSortColumnKey = "cat" | "desc" | "house" | "amt" | "ccy";

const LEDGER_SORT_OPTIONS: readonly { readonly key: LedgerSortColumnKey; readonly label: string }[] = [
  { key: "cat", label: "Category" },
  { key: "desc", label: "Description" },
  { key: "house", label: "Related property" },
  { key: "amt", label: "Monthly amount" },
  { key: "ccy", label: "Currency" },
];

function relatedHouseSortLabel(
  record: FinanceLedgerRecord,
  relatedHouseLabelByValue: ReadonlyMap<HouseKey, string>,
): string {
  if (!record.relatedHouse) return "";
  return relatedHouseLabelByValue.get(record.relatedHouse) ?? record.relatedHouse;
}

function compareLedgerRecords(
  a: FinanceLedgerRecord,
  b: FinanceLedgerRecord,
  sortKey: LedgerSortColumnKey,
  sortDir: "asc" | "desc",
  relatedHouseLabelByValue: ReadonlyMap<HouseKey, string>,
): number {
  const dir = sortDir === "asc" ? 1 : -1;
  let cmp = 0;
  switch (sortKey) {
    case "cat":
      cmp = a.category.localeCompare(b.category, undefined, { sensitivity: "base" });
      break;
    case "desc":
      cmp = a.description.localeCompare(b.description, undefined, { sensitivity: "base" });
      break;
    case "house":
      cmp = relatedHouseSortLabel(a, relatedHouseLabelByValue).localeCompare(
        relatedHouseSortLabel(b, relatedHouseLabelByValue),
        undefined,
        { sensitivity: "base" },
      );
      break;
    case "amt": {
      const ma = ledgerMonthlyAmount(a);
      const mb = ledgerMonthlyAmount(b);
      cmp = ma === mb ? 0 : ma < mb ? -1 : 1;
      break;
    }
    case "ccy":
      cmp = a.currency.localeCompare(b.currency, undefined, { sensitivity: "base" });
      break;
    default:
      break;
  }
  if (cmp !== 0) return dir * cmp;
  return a.id.localeCompare(b.id);
}

type LineFormState = {
  category: string;
  description: string;
  amount: string;
  currency: string;
  amountPeriod: FinanceLedgerAmountPeriod;
  relatedHouse: HouseKey | "";
  isTax: boolean;
  isSaving: boolean;
  isInvestment: boolean;
  isAllocate: boolean;
};

export type FinanceLedgerSheetPanelProps = {
  readonly sheetId: string;
  readonly categories: readonly string[];
  readonly records: readonly FinanceLedgerRecord[];
  readonly onPatch: (
    patch: (prev: readonly FinanceLedgerRecord[]) => FinanceLedgerRecord[],
  ) => void;
  readonly isSaving?: boolean;
  readonly formSectionTitle: string;
  readonly tableSectionTitle: string;
  readonly deleteConfirmMessage: string;
  readonly emptyMessage: string;
  readonly filterPlaceholder?: string;
  /**
   * When true (default), table rows are sorted by currency, category, related property, then
   * description (A–Z). Set false to preserve the records array order from the API.
   * After you sort via a column header, that single-column order takes precedence until you
   * reload the page.
   */
  readonly sortTableRowsByCurrencyCategoryDescription?: boolean;
  /** When true, category `<select>` options are listed A–Z (default option is first alphabetically). */
  readonly alphabetizeCategoryDropdown?: boolean;
  /** When set, shows an optional “related property” control and table column. */
  readonly relatedHouseOptions?: ReadonlyArray<{
    readonly value: HouseKey;
    readonly label: string;
  }>;
  /** Income sheet only: Tax / Saving / Investment toggles stored on each row. */
  readonly incomeFlagFields?: ReadonlyArray<{
    readonly field: IncomeLedgerFlagField;
    readonly label: string;
  }>;
  /** Expense sheet only: Allocate tag stored on each row. */
  readonly expenseFlagFields?: ReadonlyArray<{
    readonly field: ExpenseLedgerFlagField;
    readonly label: string;
  }>;
  /** Expenses sheet: persisted allocation rates for derived rows (optional). */
  readonly expenseIncomeAllocationPercents?: ExpenseIncomeAllocationPercents;
  readonly onPatchExpenseIncomeAllocationPercents?: (
    next: ExpenseIncomeAllocationPercents,
  ) => void;
  /** Expenses sheet: income ledger rows used to compute derived expense amounts. */
  readonly incomeRecordsForDerivedExpenses?: readonly FinanceLedgerRecord[];
  /** Income sheet: allocation rows tagged as income (synthetic income lines; not persisted on income). */
  readonly allocationRecordsForSyntheticIncome?: readonly FinanceAllocationRecord[];
};

function incomeLedgerFlagLabels(
  record: FinanceLedgerRecord,
  defs: FinanceLedgerSheetPanelProps["incomeFlagFields"],
): string {
  if (!defs?.length) return "";
  const parts: string[] = [];
  for (const { field, label } of defs) {
    if (record[field]) parts.push(label);
  }
  return parts.join(", ");
}

function expenseLedgerFlagLabels(
  record: FinanceLedgerRecord,
  defs: FinanceLedgerSheetPanelProps["expenseFlagFields"],
): string {
  if (!defs?.length) return "";
  const parts: string[] = [];
  for (const { field, label } of defs) {
    if (record[field]) parts.push(label);
  }
  return parts.join(", ");
}

type TaggedIncomeAllocationSectionProps = {
  readonly sheetId: string;
  readonly percents: ExpenseIncomeAllocationPercents;
  readonly onSave: (next: ExpenseIncomeAllocationPercents) => void;
};

function TaggedIncomeAllocationSection({
  sheetId,
  percents,
  onSave,
}: TaggedIncomeAllocationSectionProps) {
  const [draft, setDraft] = useState<ExpenseIncomeAllocationPercents>(percents);
  return (
    <AdminEditorSection
      title="Allocation from tagged income"
      footer={
        <button type="button" className="btn btn-primary btn-sm" onClick={() => onSave(draft)}>
          Save allocation rates
        </button>
      }
    >
      <p className="small text-muted mb-3">
        Each rate applies to monthly income on the Income tab using rows marked{" "}
        <strong>Tax</strong>, <strong>Investment</strong>, or <strong>Saving</strong>. Rows with a
        related property use that property; rows without one are grouped as &quot;no related
        property&quot;. Derived expense lines appear in the table below and cannot be edited or
        deleted.
      </p>
      <div className="row g-3">
        <div className="col-md-4">
          <label className="form-label small" htmlFor={`${sheetId}-alloc-tax`}>
            % Tax on Income
          </label>
          <input
            id={`${sheetId}-alloc-tax`}
            type="number"
            min={0}
            max={100}
            step={0.1}
            className="form-control form-control-sm"
            value={draft.taxOnIncomePercent}
            onChange={(ev) => {
              const raw = ev.target.value;
              const n = raw === "" ? 0 : Number.parseFloat(raw);
              setDraft((d) => ({
                ...d,
                taxOnIncomePercent: Number.isFinite(n)
                  ? Math.min(100, Math.max(0, n))
                  : d.taxOnIncomePercent,
              }));
            }}
          />
        </div>
        <div className="col-md-4">
          <label className="form-label small" htmlFor={`${sheetId}-alloc-inv`}>
            % Investments on Income
          </label>
          <input
            id={`${sheetId}-alloc-inv`}
            type="number"
            min={0}
            max={100}
            step={0.1}
            className="form-control form-control-sm"
            value={draft.investmentOnIncomePercent}
            onChange={(ev) => {
              const raw = ev.target.value;
              const n = raw === "" ? 0 : Number.parseFloat(raw);
              setDraft((d) => ({
                ...d,
                investmentOnIncomePercent: Number.isFinite(n)
                  ? Math.min(100, Math.max(0, n))
                  : d.investmentOnIncomePercent,
              }));
            }}
          />
        </div>
        <div className="col-md-4">
          <label className="form-label small" htmlFor={`${sheetId}-alloc-save`}>
            % Savings on Income
          </label>
          <input
            id={`${sheetId}-alloc-save`}
            type="number"
            min={0}
            max={100}
            step={0.1}
            className="form-control form-control-sm"
            value={draft.savingOnIncomePercent}
            onChange={(ev) => {
              const raw = ev.target.value;
              const n = raw === "" ? 0 : Number.parseFloat(raw);
              setDraft((d) => ({
                ...d,
                savingOnIncomePercent: Number.isFinite(n)
                  ? Math.min(100, Math.max(0, n))
                  : d.savingOnIncomePercent,
              }));
            }}
          />
        </div>
      </div>
    </AdminEditorSection>
  );
}

export function FinanceLedgerSheetPanel({
  sheetId,
  categories,
  records,
  onPatch,
  isSaving = false,
  formSectionTitle,
  tableSectionTitle,
  deleteConfirmMessage,
  emptyMessage,
  filterPlaceholder = "Filter records…",
  sortTableRowsByCurrencyCategoryDescription = true,
  alphabetizeCategoryDropdown = false,
  relatedHouseOptions,
  incomeFlagFields,
  expenseFlagFields,
  expenseIncomeAllocationPercents,
  onPatchExpenseIncomeAllocationPercents,
  incomeRecordsForDerivedExpenses,
  allocationRecordsForSyntheticIncome,
}: FinanceLedgerSheetPanelProps) {
  const showRelatedHouseCol = Boolean(relatedHouseOptions?.length);
  const showIncomeFlagsCol = Boolean(incomeFlagFields?.length);
  const showExpenseFlagsCol = Boolean(expenseFlagFields?.length);

  const relatedHouseLabelByValue = useMemo(() => {
    const m = new Map<HouseKey, string>();
    if (!relatedHouseOptions) return m;
    for (const o of relatedHouseOptions) {
      m.set(o.value, o.label);
    }
    return m;
  }, [relatedHouseOptions]);

  const showExpenseAllocationBlock =
    sheetId === "expenses" &&
    Boolean(
      expenseIncomeAllocationPercents &&
        onPatchExpenseIncomeAllocationPercents &&
        incomeRecordsForDerivedExpenses,
    );

  const tableSourceRecords = useMemo((): readonly FinanceLedgerRecord[] => {
    if (sheetId === "income" && allocationRecordsForSyntheticIncome?.length) {
      const synthetic = syntheticIncomeLedgerRowsFromAllocations(
        allocationRecordsForSyntheticIncome,
      );
      return [...synthetic, ...records];
    }
    if (
      sheetId !== "expenses" ||
      !expenseIncomeAllocationPercents ||
      !incomeRecordsForDerivedExpenses ||
      !relatedHouseOptions?.length
    ) {
      return records;
    }
    const derived = buildDerivedExpenseLedgerRowsFromTaggedIncome(
      incomeRecordsForDerivedExpenses,
      expenseIncomeAllocationPercents,
      relatedHouseOptions,
    );
    return [...derived, ...records];
  }, [
    sheetId,
    records,
    allocationRecordsForSyntheticIncome,
    expenseIncomeAllocationPercents,
    incomeRecordsForDerivedExpenses,
    relatedHouseOptions,
  ]);

  const [sortKey, setSortKey] = useState<LedgerSortColumnKey | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const onLedgerSort = useCallback((key: LedgerSortColumnKey) => {
    setSortKey((prevKey) => {
      if (prevKey !== key) {
        setSortDir("asc");
        return key;
      }
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      return prevKey;
    });
  }, []);

  const tableColumns = useMemo((): AdminDataTableColumn[] => {
    const manualSort = sortKey !== null;
    const thAria = (
      key: LedgerSortColumnKey,
    ): "ascending" | "descending" | "none" | "other" | undefined => {
      if (!manualSort) return undefined;
      if (sortKey === key) return sortDir === "asc" ? "ascending" : "descending";
      return "none";
    };
    const dirFor = (key: LedgerSortColumnKey): "asc" | "desc" | null =>
      sortKey === key ? sortDir : null;

    const cols: AdminDataTableColumn[] = [
      {
        key: "cat",
        header: (
          <TableSortHeaderButton
            label="Category"
            isActive={sortKey === "cat"}
            direction={dirFor("cat")}
            onClick={() => onLedgerSort("cat")}
          />
        ),
        className: "small",
        priority: "secondary",
        thAriaSort: thAria("cat"),
      },
      {
        key: "desc",
        header: (
          <TableSortHeaderButton
            label="Description"
            isActive={sortKey === "desc"}
            direction={dirFor("desc")}
            onClick={() => onLedgerSort("desc")}
          />
        ),
        className: "small",
        thAriaSort: thAria("desc"),
      },
    ];
    if (showIncomeFlagsCol || showExpenseFlagsCol) {
      cols.push({
        key: "flags",
        header: <span className="fw-semibold admin-nowrap">Tags</span>,
        className: "small",
        priority: "secondary",
      });
    }
    if (showRelatedHouseCol) {
      cols.push({
        key: "house",
        header: (
          <TableSortHeaderButton
            label="Related property"
            isActive={sortKey === "house"}
            direction={dirFor("house")}
            onClick={() => onLedgerSort("house")}
          />
        ),
        className: "small",
        priority: "tertiary",
        thAriaSort: thAria("house"),
      });
    }
    cols.push(
      {
        key: "amt",
        header: (
          <TableSortHeaderButton
            label="Monthly amount"
            isActive={sortKey === "amt"}
            direction={dirFor("amt")}
            onClick={() => onLedgerSort("amt")}
            align="end"
          />
        ),
        className: "small text-end",
        headerClassName: "small text-end",
        thAriaSort: thAria("amt"),
      },
      {
        key: "ccy",
        header: (
          <TableSortHeaderButton
            label="Currency"
            isActive={sortKey === "ccy"}
            direction={dirFor("ccy")}
            onClick={() => onLedgerSort("ccy")}
          />
        ),
        className: "small",
        priority: "secondary",
        thAriaSort: thAria("ccy"),
      },
      {
        key: "ops",
        header: <span className="visually-hidden">Operations</span>,
        className: "text-end admin-nowrap",
        headerClassName: "text-end",
      },
    );
    return cols;
  }, [showRelatedHouseCol, showIncomeFlagsCol, showExpenseFlagsCol, sortKey, sortDir, onLedgerSort]);
  const colSpan = tableColumns.length;
  const ledgerSortOptions = useMemo(
    () =>
      LEDGER_SORT_OPTIONS.filter((o) => o.key !== "house" || showRelatedHouseCol),
    [showRelatedHouseCol],
  );

  const formId = `${sheetId}-ledger-form`;
  const categoryOptions = useMemo(() => {
    const list = [...categories];
    if (alphabetizeCategoryDropdown) {
      list.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
    }
    return list;
  }, [categories, alphabetizeCategoryDropdown]);
  const defaultCategory = categoryOptions[0] ?? "";
  const emptyForm = (): LineFormState => ({
    category: defaultCategory,
    description: "",
    amount: "",
    currency: GLOBAL_DEFAULT_CURRENCY,
    amountPeriod: "month",
    relatedHouse: "",
    isTax: false,
    isSaving: false,
    isInvestment: false,
    isAllocate: false,
  });

  const expanded = useExpandedRecord(sheetId);
  const editingId =
    expanded.expandedId && expanded.expandedId !== DRAFT_RECORD_ID
      ? expanded.expandedId
      : null;
  const formOpen = expanded.expandedId !== null;
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [lineForm, setLineForm] = useState<LineFormState>(() => emptyForm());
  const [tableFilter, setTableFilter] = useState("");
  const [totalDisplayCurrency, setTotalDisplayCurrency] = useState<CurrencyCode>(
    GLOBAL_DEFAULT_CURRENCY,
  );

  const filtered = useMemo(() => {
    const q = tableFilter.trim().toLowerCase();
    const list = !q
      ? [...tableSourceRecords]
      : tableSourceRecords.filter((r) => {
          const houseHay =
            r.relatedHouse && relatedHouseLabelByValue.get(r.relatedHouse)
              ? relatedHouseLabelByValue.get(r.relatedHouse)
              : r.relatedHouse ?? "";
          const flagHay = incomeLedgerFlagLabels(r, incomeFlagFields).toLowerCase();
          const expenseFlagHay = expenseLedgerFlagLabels(r, expenseFlagFields).toLowerCase();
          const derivedAllocHay = r.isDerivedFromTaggedIncome ? "allocate" : "";
          const derivedIncHay = r.isDerivedFromAllocation ? "allocation" : "";
          const hay = [
            r.category,
            r.description,
            r.currency,
            r.amountPeriod,
            String(r.amount),
            houseHay ?? "",
            flagHay,
            expenseFlagHay,
            derivedAllocHay,
            derivedIncHay,
          ]
            .join(" ")
            .toLowerCase();
          return hay.includes(q);
        });
    if (sortKey !== null) {
      list.sort((a, b) =>
        compareLedgerRecords(a, b, sortKey, sortDir, relatedHouseLabelByValue),
      );
    } else if (sortTableRowsByCurrencyCategoryDescription) {
      list.sort((a, b) => {
        const byCcy = a.currency.localeCompare(b.currency, undefined, { sensitivity: "base" });
        if (byCcy !== 0) return byCcy;
        const byCat = a.category.localeCompare(b.category, undefined, { sensitivity: "base" });
        if (byCat !== 0) return byCat;
        const byHouse = (a.relatedHouse ?? "").localeCompare(b.relatedHouse ?? "", undefined, {
          sensitivity: "base",
        });
        if (byHouse !== 0) return byHouse;
        return a.description.localeCompare(b.description, undefined, { sensitivity: "base" });
      });
    }
    return list;
  }, [
    tableSourceRecords,
    tableFilter,
    sortTableRowsByCurrencyCategoryDescription,
    relatedHouseLabelByValue,
    sortKey,
    sortDir,
    incomeFlagFields,
    expenseFlagFields,
  ]);

  const recordCurrencies = useMemo(
    () => filtered.map((r) => r.currency),
    [filtered],
  );

  const { needsFx, ratesQuery, fxLoading, fxError } = useFrankfurterRatesForTotals(
    totalDisplayCurrency,
    recordCurrencies,
  );

  const convertedTotal = useMemo(() => {
    if (filtered.length === 0) {
      return tableSourceRecords.length === 0 ? null : 0;
    }
    let map: ReadonlyMap<string, number> = new Map();
    if (needsFx) {
      if (!ratesQuery.isSuccess) return null;
      const ratePayload = ratesQuery.data;
      if (!ratePayload) return null;
      map = ratePayload.rateByQuote;
    }
    try {
      return filtered.reduce(
        (sum, r) =>
          sum +
          convertAmountToBase(
            ledgerMonthlyAmount(r),
            r.currency,
            totalDisplayCurrency,
            map,
          ),
        0,
      );
    } catch {
      return null;
    }
  }, [
    filtered,
    tableSourceRecords.length,
    needsFx,
    ratesQuery.isSuccess,
    ratesQuery.data,
    totalDisplayCurrency,
  ]);

  function resetFields() {
    setFormError(null);
    setLineForm(emptyForm());
  }

  function formFromLedger(row: FinanceLedgerRecord): LineFormState {
    return {
      category: row.category,
      description: row.description,
      amount: String(row.amount),
      currency: row.currency,
      amountPeriod: row.amountPeriod,
      relatedHouse: row.relatedHouse ?? "",
      isTax: row.isTax === true,
      isSaving: row.isSaving === true,
      isInvestment: row.isInvestment === true,
      isAllocate: row.isAllocate === true,
    };
  }

  function applyLedger(row: FinanceLedgerRecord) {
    setFormError(null);
    setLineForm(formFromLedger(row));
  }

  function ledgerDirty(): boolean {
    if (!formOpen) return false;
    if (!editingId) return JSON.stringify(lineForm) !== JSON.stringify(emptyForm());
    const row = tableSourceRecords.find((record) => record.id === editingId);
    if (!row || row.isDerivedFromTaggedIncome || row.isDerivedFromAllocation) return false;
    return JSON.stringify(lineForm) !== JSON.stringify(formFromLedger(row));
  }

  const editingLedger = editingId
    ? (tableSourceRecords.find((record) => record.id === editingId) ?? null)
    : null;
  const editableLedger =
    editingLedger && !editingLedger.isDerivedFromTaggedIncome && !editingLedger.isDerivedFromAllocation
      ? editingLedger
      : null;
  useHydrateExpandedRecord({
    expandedId: expanded.expandedId,
    recordsReady: true,
    record: editableLedger,
    apply: applyLedger,
    onMissing: () => expanded.request(null, false),
  });

  function openEdit(row: FinanceLedgerRecord) {
    if (row.isDerivedFromTaggedIncome || row.isDerivedFromAllocation) return;
    expanded.toggle(row.id, ledgerDirty(), () => applyLedger(row), resetFields);
  }

  function openCreate() {
    if (expanded.expandedId === DRAFT_RECORD_ID) {
      expanded.request(null, ledgerDirty(), resetFields);
      return;
    }
    expanded.request(DRAFT_RECORD_ID, ledgerDirty(), resetFields);
  }

  function submitLine(e: FormEvent) {
    e.preventDefault();
    const amount = parseAmount(lineForm.amount);
    if (!lineForm.description.trim()) {
      setFormError("Description is required.");
      return;
    }
    if (amount === null) {
      setFormError("Amount must be a valid number.");
      return;
    }
    if (!categories.includes(lineForm.category)) {
      setFormError("Pick a valid category.");
      return;
    }
    const currency = coerceSupportedCurrency(lineForm.currency, GLOBAL_DEFAULT_CURRENCY);
    const row: FinanceLedgerRecord = {
      id: editingId ?? newStatementLineId(),
      category: lineForm.category,
      description: lineForm.description.trim(),
      amount,
      currency,
      amountPeriod: lineForm.amountPeriod,
      ...(lineForm.relatedHouse === "hillmarton" || lineForm.relatedHouse === "morrison"
        ? { relatedHouse: lineForm.relatedHouse }
        : {}),
      ...(incomeFlagFields?.length
        ? {
            isTax: lineForm.isTax,
            isSaving: lineForm.isSaving,
            isInvestment: lineForm.isInvestment,
          }
        : {}),
      ...(expenseFlagFields?.length ? { isAllocate: lineForm.isAllocate } : {}),
    };

    onPatch((prev) => {
      if (editingId) {
        return prev.map((r) => (r.id === editingId ? row : r));
      }
      return [...prev, row];
    });

    resetFields();
    expanded.request(null, false);
  }

  function deleteRow(id: string) {
    const row = tableSourceRecords.find((r) => r.id === id);
    if (row?.isDerivedFromTaggedIncome || row?.isDerivedFromAllocation) {
      return;
    }
    onPatch((prev) => prev.filter((r) => r.id !== id));
    if (editingId === id) {
      resetFields();
      expanded.request(null, false);
    }
    setPendingDeleteId(null);
  }

                  const ledgerEditor = formOpen ? (
        <AdminEditorPanel
          formId={formId}
          onSubmit={submitLine}
          submitLabel={editingId ? "Update record" : "Add record"}
          isSaving={isSaving}
          error={formError}
        >
          <span className="visually-hidden">{formSectionTitle}</span>
          <div className="row g-3">
            <div className={showRelatedHouseCol ? "col-md-2" : "col-md-3"}>
              <label className="form-label small" htmlFor={`${sheetId}-ledger-cat`}>
                Category
              </label>
              <select
                id={`${sheetId}-ledger-cat`}
                className="form-select form-select-sm"
                value={lineForm.category}
                onChange={(ev) =>
                  setLineForm((f) => ({ ...f, category: ev.target.value }))
                }
              >
                {categoryOptions.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <div className={showRelatedHouseCol ? "col-md-2" : "col-md-3"}>
              <label className="form-label small" htmlFor={`${sheetId}-ledger-desc`}>
                Description
              </label>
              <input
                id={`${sheetId}-ledger-desc`}
                type="text"
                className="form-control form-control-sm"
                required
                value={lineForm.description}
                onChange={(ev) =>
                  setLineForm((f) => ({ ...f, description: ev.target.value }))
                }
              />
            </div>
            {showRelatedHouseCol ? (
              <div className="col-md-2">
                <label className="form-label small" htmlFor={`${sheetId}-ledger-house`}>
                  Related property
                </label>
                <select
                  id={`${sheetId}-ledger-house`}
                  className="form-select form-select-sm"
                  value={lineForm.relatedHouse}
                  onChange={(ev) =>
                    setLineForm((f) => ({
                      ...f,
                      relatedHouse: ev.target.value as HouseKey | "",
                    }))
                  }
                >
                  <option value="">— None —</option>
                  {(relatedHouseOptions ?? []).map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="col-md-2">
              <label className="form-label small" htmlFor={`${sheetId}-ledger-amt`}>
                Amount
              </label>
              <input
                id={`${sheetId}-ledger-amt`}
                type="number"
                step="0.01"
                className="form-control form-control-sm"
                required
                value={lineForm.amount}
                onChange={(ev) =>
                  setLineForm((f) => ({ ...f, amount: ev.target.value }))
                }
              />
            </div>
            <div className="col-md-2">
              <label className="form-label small" htmlFor={`${sheetId}-ledger-period`}>
                Amount is
              </label>
              <select
                id={`${sheetId}-ledger-period`}
                className="form-select form-select-sm"
                value={lineForm.amountPeriod}
                onChange={(ev) =>
                  setLineForm((f) => ({
                    ...f,
                    amountPeriod: ev.target.value as FinanceLedgerAmountPeriod,
                  }))
                }
              >
                <option value="month">Per month</option>
                <option value="year">Per year</option>
              </select>
            </div>
            <div className="col-md-2">
              <label className="form-label small" htmlFor={`${sheetId}-ledger-ccy`}>
                Currency
              </label>
              <CurrencySelect
                id={`${sheetId}-ledger-ccy`}
                value={lineForm.currency}
                onChange={(code) =>
                  setLineForm((f) => ({ ...f, currency: code }))
                }
              />
            </div>
          </div>
          {showIncomeFlagsCol && incomeFlagFields ? (
            <div className="row g-3 mt-0">
              <div className="col-12">
                <span className="form-label small d-block mb-1">Tags</span>
                <div className="d-flex flex-wrap gap-3">
                  {incomeFlagFields.map(({ field, label }) => (
                    <div key={field} className="form-check mb-0">
                      <input
                        id={`${sheetId}-ledger-${field}`}
                        type="checkbox"
                        className="form-check-input"
                        checked={lineForm[field]}
                        onChange={(ev) =>
                          setLineForm((f) => ({ ...f, [field]: ev.target.checked }))
                        }
                      />
                      <label
                        className="form-check-label small"
                        htmlFor={`${sheetId}-ledger-${field}`}
                      >
                        {label}
                      </label>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
          {showExpenseFlagsCol && expenseFlagFields ? (
            <div className="row g-3 mt-0">
              <div className="col-12">
                <span className="form-label small d-block mb-1">Tags</span>
                <div className="d-flex flex-wrap gap-3">
                  {expenseFlagFields.map(({ field, label }) => (
                    <div key={field} className="form-check mb-0">
                      <input
                        id={`${sheetId}-ledger-${field}`}
                        type="checkbox"
                        className="form-check-input"
                        checked={lineForm[field]}
                        onChange={(ev) =>
                          setLineForm((f) => ({ ...f, [field]: ev.target.checked }))
                        }
                      />
                      <label
                        className="form-check-label small"
                        htmlFor={`${sheetId}-ledger-${field}`}
                      >
                        {label}
                      </label>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </AdminEditorPanel>
      ) : null;

  return (
    <div>
      {showExpenseAllocationBlock &&
      expenseIncomeAllocationPercents &&
      onPatchExpenseIncomeAllocationPercents ? (
        <TaggedIncomeAllocationSection
          key={JSON.stringify(expenseIncomeAllocationPercents)}
          sheetId={sheetId}
          percents={expenseIncomeAllocationPercents}
          onSave={onPatchExpenseIncomeAllocationPercents}
        />
      ) : null}
      <AdminRecordTable
        label={tableSectionTitle}
        filters={
          <AdminFilterBar create={<AdminCreateButton label={sheetId === "income" ? "New income" : "New expense"} onClick={openCreate} />}>
            <AdminFilterField label="Filter" htmlFor={`${sheetId}-ledger-filter`}>
              <input id={`${sheetId}-ledger-filter`} type="search" className="form-control form-control-sm" placeholder={filterPlaceholder} autoComplete="off" value={tableFilter} onChange={(ev) => setTableFilter(ev.target.value)} />
            </AdminFilterField>
          </AdminFilterBar>
        }
      >
        <AdminDataTable
          bare
          columns={tableColumns}
          sort={{
            options: ledgerSortOptions,
            sortKey,
            direction: sortDir,
            onChange: (key, dir) => {
              setSortKey(key as LedgerSortColumnKey | null);
              setSortDir(dir);
            },
          }}
        >
          {expanded.expandedId === DRAFT_RECORD_ID ? (
            <AdminExpandableRow colSpan={colSpan} expanded onToggle={openCreate} editor={ledgerEditor}>
              {tableColumns.map((col) => (
                <AdminCell key={col.key} column={col.key}>
                  {col.key === "desc" ? "New record" : null}
                </AdminCell>
              ))}
            </AdminExpandableRow>
          ) : null}
          {filtered.length ? (
            filtered.map((r) => {
              const flagsLabel = showIncomeFlagsCol
                ? r.isDerivedFromAllocation
                  ? "Allocation"
                  : incomeLedgerFlagLabels(r, incomeFlagFields)
                : showExpenseFlagsCol
                  ? r.isDerivedFromTaggedIncome
                    ? "Allocate"
                    : expenseLedgerFlagLabels(r, expenseFlagFields)
                  : "";
              const houseLabel = r.relatedHouse
                ? (relatedHouseLabelByValue.get(r.relatedHouse) ?? r.relatedHouse)
                : "";
              const editable = !r.isDerivedFromTaggedIncome && !r.isDerivedFromAllocation;
              return (
              <AdminExpandableRow
                key={r.id}
                colSpan={colSpan}
                expanded={expanded.expandedId === r.id}
                onToggle={() => openEdit(r)}
                editor={editable ? ledgerEditor : null}
              >
                <AdminCell column="cat" className="small">{r.category}</AdminCell>
                <AdminCell column="desc" className="small">
                  {r.description}
                  <AdminDataTableCellMeta>
                    {[r.category, flagsLabel, r.currency].filter(Boolean).join(" · ")}
                  </AdminDataTableCellMeta>
                  {showRelatedHouseCol && houseLabel ? (
                    <AdminDataTableCellMeta until="tertiary">{houseLabel}</AdminDataTableCellMeta>
                  ) : null}
                </AdminCell>
                {showIncomeFlagsCol || showExpenseFlagsCol ? (
                  <AdminCell column="flags" className="small text-muted">
                    {flagsLabel || "—"}
                  </AdminCell>
                ) : null}
                {showRelatedHouseCol ? (
                  <AdminCell column="house" className="small text-muted">
                    {houseLabel || "—"}
                  </AdminCell>
                ) : null}
                <AdminCell column="amt" className="small text-end">
                  <MoneyAmount
                    amount={ledgerMonthlyAmount(r)}
                    currency={r.currency}
                    amountOnly
                  />
                </AdminCell>
                <AdminCell column="ccy" className="small">{r.currency}</AdminCell>
                <AdminCell column="ops" className="small text-end">
                  {r.isDerivedFromTaggedIncome ? (
                    <span className="text-muted small">Derived</span>
                  ) : r.isDerivedFromAllocation ? (
                    <span className="visually-hidden">No operations</span>
                  ) : (
                    <AdminRowActions
                      actions={[
                        { id: "edit", label: "Edit record", iconClassName: "bi bi-pencil", onClick: () => openEdit(r) },
                        { id: "delete", label: "Delete record", iconClassName: "bi bi-trash", danger: true, onClick: () => setPendingDeleteId(r.id) },
                      ]}
                    />
                  )}
                </AdminCell>
              </AdminExpandableRow>
              );
            })
          ) : (
            <AdminDataTableEmptyRow
              colSpan={colSpan}
              message={
                tableSourceRecords.length
                  ? "No records match the filter."
                  : emptyMessage
              }
            />
          )}
          {tableSourceRecords.length > 0 ? (
            <tr className="table-group-divider table-secondary fw-semibold">
              <AdminCell column="cat" className="small" />
              <AdminCell column="desc" className="small">
                <AdminTableTotalLabel
                  needsFx={needsFx}
                  fxError={fxError}
                  fxLoading={fxLoading}
                  ratesQuery={ratesQuery}
                />
              </AdminCell>
              {showIncomeFlagsCol || showExpenseFlagsCol ? (
                <AdminCell column="flags" className="small" />
              ) : null}
              {showRelatedHouseCol ? <AdminCell column="house" className="small" /> : null}
              <AdminCell column="amt" className="small text-end">
                {convertedTotal !== null ? (
                  <MoneyAmount
                    amount={convertedTotal}
                    currency={totalDisplayCurrency}
                    amountOnly
                  />
                ) : (
                  <span className="text-muted">—</span>
                )}
                <br />
                <AdminTableTotalCurrency
                  id={`${sheetId}-ledger-total-ccy`}
                  value={totalDisplayCurrency}
                  onChange={setTotalDisplayCurrency}
                  disabled={fxLoading}
                />
              </AdminCell>
              <AdminCell column="ccy" className="small" />
              <AdminCell column="ops" className="small text-end" />
            </tr>
          ) : null}
        </AdminDataTable>
        <ConfirmDialog open={pendingDeleteId !== null} title="Delete record" body={deleteConfirmMessage} confirmLabel="Delete" tone="danger" onConfirm={() => { if (pendingDeleteId) deleteRow(pendingDeleteId); }} onCancel={() => setPendingDeleteId(null)} />
        <ConfirmDialog open={expanded.confirmOpen} title="Discard unsaved edits?" body="This record has unsaved changes." confirmLabel="Discard" cancelLabel="Keep editing" tone="danger" onConfirm={expanded.acceptPending} onCancel={expanded.cancelPending} />
      </AdminRecordTable>
    </div>
  );
}
