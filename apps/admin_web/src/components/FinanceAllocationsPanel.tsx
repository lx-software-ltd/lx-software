import { type FormEvent, useMemo, useState } from "react";
import { compareBy } from "../lib/compareBy";
import {
  coerceSupportedCurrency,
  GLOBAL_DEFAULT_CURRENCY,
  type CurrencyCode,
} from "../lib/currencies";
import { formatDateUtc } from "../lib/formatDisplay";
import { parseAmount } from "../lib/formParse";
import { convertAmountToBase } from "../lib/frankfurterRates";
import { DRAFT_RECORD_ID } from "../lib/expandedRecord";
import { useRecordEditor } from "../hooks/useRecordEditor";
import { useSortState } from "../hooks/useSortState";
import {
  CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX,
  type FinanceAllocationRecord,
  newCustomAllocationExpenseId,
} from "../lib/financeModel";
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
  AdminField,
  AdminFieldGrid,
  AdminFxTotalRow,
  AdminFilterBar,
  AdminFilterField,
  AdminRecordTable,
  AdminRowActions,
  ConfirmDialog,
  CurrencySelect,
  MoneyAmount,
  TableSortHeaderButton,
} from "./ui";

type AllocSortKey = "desc" | "monthly" | "accum" | "ccy" | "last";

function allocationLastUpdatedDisplay(lastUpdated: string | undefined): string {
  if (!lastUpdated) {
    return "—";
  }
  return formatDateUtc(`${lastUpdated}T00:00:00.000Z`);
}

/** Linked rows mirror an expense tagged Allocate; custom rows are created on the Allocations tab. */
function allocationTagsCellLabel(r: FinanceAllocationRecord): string {
  const isCustom =
    r.isCustomAllocation === true || r.expenseId.startsWith(CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX);
  const parts: string[] = [];
  if (!isCustom) {
    parts.push("Expenses");
  } else if (r.isIncome === true) {
    parts.push("Income");
  }
  if (r.isPension === true) {
    parts.push("Pension");
  }
  if (parts.length === 0) {
    return "—";
  }
  return parts.join(", ");
}

function compareAllocations(
  a: FinanceAllocationRecord,
  b: FinanceAllocationRecord,
  sortKey: AllocSortKey,
  sortDir: "asc" | "desc",
): number {
  return compareBy(
    a,
    b,
    sortDir,
    (left, right) => {
      switch (sortKey) {
        case "desc":
          return left.description.localeCompare(right.description, undefined, { sensitivity: "base" });
        case "monthly":
          return left.monthlyAmount === right.monthlyAmount
            ? 0
            : left.monthlyAmount < right.monthlyAmount
              ? -1
              : 1;
        case "accum":
          return left.accumulatedAmount === right.accumulatedAmount
            ? 0
            : left.accumulatedAmount < right.accumulatedAmount
              ? -1
              : 1;
        case "ccy":
          return left.currency.localeCompare(right.currency, undefined, { sensitivity: "base" });
        case "last": {
          const sa = left.lastUpdated ?? "";
          const sb = right.lastUpdated ?? "";
          if (!sa && !sb) return 0;
          if (!sa) return 1;
          if (!sb) return -1;
          return sa.localeCompare(sb);
        }
        default:
          return 0;
      }
    },
    (left, right) => left.expenseId.localeCompare(right.expenseId),
  );
}

/** Linked row patch from editor: optional Income and Pension tags (omit when unchecked). */
function linkedStoredRowPatch(
  row: FinanceAllocationRecord,
  accumulatedAmount: number,
  flags: { readonly isIncome: boolean; readonly isPension: boolean },
): FinanceAllocationRecord {
  return {
    expenseId: row.expenseId,
    description: row.description,
    monthlyAmount: row.monthlyAmount,
    accumulatedAmount,
    currency: row.currency,
    ...(row.lastUpdated !== undefined ? { lastUpdated: row.lastUpdated } : {}),
    ...(row.relatedHouse !== undefined ? { relatedHouse: row.relatedHouse } : {}),
    ...(flags.isIncome ? { isIncome: true as const } : {}),
    ...(flags.isPension ? { isPension: true as const } : {}),
  };
}

function allocationMonthlyColumnDisplay(
  row: FinanceAllocationRecord,
): { readonly kind: "dash" } | { readonly kind: "amount"; readonly value: number; readonly currency: string } {
  if (row.isCustomAllocation === true) {
    if (row.isIncome === true) {
      return {
        kind: "amount",
        value: row.allocationIncomeMonthly ?? 0,
        currency: row.currency,
      };
    }
    return { kind: "dash" };
  }
  return { kind: "amount", value: row.monthlyAmount, currency: row.currency };
}

type AllocationFormState = {
  description: string;
  currency: CurrencyCode;
  accumulated: string;
  isIncome: boolean;
  isPension: boolean;
  incomeMonthly: string;
};

function emptyAllocationForm(): AllocationFormState {
  return {
    description: "",
    currency: GLOBAL_DEFAULT_CURRENCY,
    accumulated: "",
    isIncome: false,
    isPension: false,
    incomeMonthly: "",
  };
}

function lineToForm(row: FinanceAllocationRecord): AllocationFormState {
  if (row.isCustomAllocation === true) {
    return {
      description: row.description,
      currency: coerceSupportedCurrency(row.currency, GLOBAL_DEFAULT_CURRENCY),
      accumulated: String(row.accumulatedAmount),
      isIncome: row.isIncome === true,
      isPension: row.isPension === true,
      incomeMonthly:
        row.allocationIncomeMonthly !== undefined ? String(row.allocationIncomeMonthly) : "",
    };
  }
  return {
    ...emptyAllocationForm(),
    accumulated: String(row.accumulatedAmount),
    isIncome: row.isIncome === true,
    isPension: row.isPension === true,
  };
}

export function FinanceAllocationsPanel(props: {
  readonly records: readonly FinanceAllocationRecord[];
  readonly onPatch: (
    patch: (prev: readonly FinanceAllocationRecord[]) => FinanceAllocationRecord[],
  ) => void;
  readonly isSaving?: boolean;
}) {
  const { records, onPatch, isSaving = false } = props;
  const { sortKey, sortDir, onSort, ariaSort, directionFor } = useSortState<AllocSortKey>(null);

  const tableColumns = useMemo((): AdminDataTableColumn[] => {

    return [
      {
        key: "desc",
        header: (
          <TableSortHeaderButton
            label="Description"
            isActive={sortKey === "desc"}
            direction={directionFor("desc")}
            onClick={() => onSort("desc")}
          />
        ),
        className: "small",
        thAriaSort: ariaSort("desc"),
      },
      {
        key: "tags",
        header: <span className="fw-semibold admin-nowrap">Tags</span>,
        className: "small text-muted",
        priority: "secondary",
      },
      {
        key: "monthly",
        header: (
          <TableSortHeaderButton
            label="Monthly amount"
            isActive={sortKey === "monthly"}
            direction={directionFor("monthly")}
            align="end"
            onClick={() => onSort("monthly")}
          />
        ),
        className: "small text-end",
        headerClassName: "small text-end",
        // Accumulated is what this tab edits and totals, so it stays on phones; monthly moves to md+.
        priority: "secondary",
        thAriaSort: ariaSort("monthly"),
      },
      {
        key: "accum",
        header: (
          <TableSortHeaderButton
            label="Accumulated amount"
            isActive={sortKey === "accum"}
            direction={directionFor("accum")}
            align="end"
            onClick={() => onSort("accum")}
          />
        ),
        className: "small text-end",
        headerClassName: "small text-end",
        thAriaSort: ariaSort("accum"),
      },
      {
        key: "last",
        header: (
          <TableSortHeaderButton
            label="Last update"
            isActive={sortKey === "last"}
            direction={directionFor("last")}
            onClick={() => onSort("last")}
          />
        ),
        className: "small admin-nowrap",
        priority: "tertiary",
        thAriaSort: ariaSort("last"),
      },
      {
        key: "ops",
        header: <span className="visually-hidden">Operations</span>,
        className: "text-end admin-nowrap",
        headerClassName: "text-end",
      },
    ];
  }, [ariaSort, directionFor, onSort, sortKey]);

  const colSpan = tableColumns.length;

  const [tableFilter, setTableFilter] = useState("");
  const editor = useRecordEditor<AllocationFormState, FinanceAllocationRecord>({
    param: "allocation",
    records,
    idOf: (row) => row.expenseId,
    emptyForm: emptyAllocationForm,
    lineToForm,
    onDelete: (id) => {
      onPatch((prev) => prev.filter((row) => row.expenseId !== id));
    },
  });
  const form = editor.form;
  const formOpen = editor.formOpen;
  const editingRow = editor.editingRecord ?? undefined;
  const editingLinkedRow =
    editingRow && editingRow.isCustomAllocation !== true ? editingRow : undefined;
  const editingCustomExpenseId =
    editingRow?.isCustomAllocation === true ? editingRow.expenseId : null;
  const customDesc = form.description;
  const customCcy = form.currency;
  const customAccumStr = form.accumulated;
  const customIsIncome = form.isIncome;
  const customIsPension = form.isPension;
  const customIncomeMonthlyStr = form.incomeMonthly;
  const linkedAccumStr = form.accumulated;
  const linkedIsIncome = form.isIncome;
  const linkedIsPension = form.isPension;
  const linkedFormError = editor.formError;
  const customFormError = editor.formError;
  const setLinkedAccumStr = (value: string) => {
    editor.setForm((prev) => ({ ...prev, accumulated: value }));
  };
  const setLinkedIsIncome = (value: boolean) => {
    editor.setForm((prev) => ({ ...prev, isIncome: value }));
  };
  const setLinkedIsPension = (value: boolean) => {
    editor.setForm((prev) => ({ ...prev, isPension: value }));
  };
  const setLinkedFormError = editor.setFormError;
  const setCustomDesc = (value: string) => {
    editor.setForm((prev) => ({ ...prev, description: value }));
  };
  const setCustomCcy = (value: CurrencyCode) => {
    editor.setForm((prev) => ({ ...prev, currency: value }));
  };
  const setCustomAccumStr = (value: string) => {
    editor.setForm((prev) => ({ ...prev, accumulated: value }));
  };
  const setCustomIsIncome = (value: boolean) => {
    editor.setForm((prev) => ({ ...prev, isIncome: value }));
  };
  const setCustomIsPension = (value: boolean) => {
    editor.setForm((prev) => ({ ...prev, isPension: value }));
  };
  const setCustomIncomeMonthlyStr = (value: string) => {
    editor.setForm((prev) => ({ ...prev, incomeMonthly: value }));
  };
  const setCustomFormError = editor.setFormError;
  const [totalDisplayCurrency, setTotalDisplayCurrency] = useState<CurrencyCode>(
    GLOBAL_DEFAULT_CURRENCY,
  );

  const filtered = useMemo(() => {
    const q = tableFilter.trim().toLowerCase();
    const list = !q
      ? [...records]
      : records.filter((r) => {
          const hay = [r.description, r.currency, String(r.monthlyAmount), String(r.accumulatedAmount)]
            .join(" ")
            .toLowerCase();
          const tagHay = allocationTagsCellLabel(r).toLowerCase();
          return `${hay} ${tagHay}`.includes(q);
        });
    if (sortKey !== null) {
      list.sort((a, b) => compareAllocations(a, b, sortKey, sortDir));
    } else {
      list.sort((a, b) =>
        a.description.localeCompare(b.description, undefined, { sensitivity: "base" }),
      );
    }
    return list;
  }, [records, tableFilter, sortKey, sortDir]);

  const recordCurrencies = useMemo(() => filtered.map((r) => r.currency), [filtered]);

  const { needsFx, ratesQuery, fxLoading, fxError } = useFrankfurterRatesForTotals(
    totalDisplayCurrency,
    recordCurrencies,
  );

  const convertedAccumulatedTotal = useMemo(() => {
    if (filtered.length === 0) {
      return records.length === 0 ? null : 0;
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
            r.accumulatedAmount,
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
    records.length,
    needsFx,
    ratesQuery.isSuccess,
    ratesQuery.data,
    totalDisplayCurrency,
  ]);

  const editorFormId = "finance-allocations-editor-form";

  function submitCustomAllocationCore() {
    const d = customDesc.trim();
    if (!d) {
      setCustomFormError("Description is required.");
      return;
    }
    const n = parseAmount(customAccumStr);
    if (n === null) {
      setCustomFormError("Accumulated amount must be a valid number.");
      return;
    }
    const ccy = coerceSupportedCurrency(customCcy, GLOBAL_DEFAULT_CURRENCY);
    if (customIsIncome) {
      const inc = parseAmount(customIncomeMonthlyStr);
      if (inc === null) {
        setCustomFormError("Monthly income amount must be a valid number.");
        return;
      }
      if (inc <= 0) {
        setCustomFormError("Monthly income amount must be positive when Income is checked.");
        return;
      }
      if (editingCustomExpenseId) {
        onPatch((prev) =>
          prev.map((r) =>
            r.expenseId === editingCustomExpenseId
              ? {
                  expenseId: r.expenseId,
                  description: d,
                  currency: ccy,
                  accumulatedAmount: n,
                  monthlyAmount: 0,
                  isCustomAllocation: true as const,
                  isIncome: true as const,
                  allocationIncomeMonthly: inc,
                  ...(customIsPension ? { isPension: true as const } : {}),
                }
              : r,
          ),
        );
      } else {
        onPatch((prev) => [
          ...prev,
          {
            expenseId: newCustomAllocationExpenseId(),
            description: d,
            monthlyAmount: 0,
            accumulatedAmount: n,
            currency: ccy,
            isCustomAllocation: true as const,
            isIncome: true as const,
            allocationIncomeMonthly: inc,
            ...(customIsPension ? { isPension: true as const } : {}),
          },
        ]);
      }
    } else if (editingCustomExpenseId) {
      onPatch((prev) =>
        prev.map((r) =>
          r.expenseId === editingCustomExpenseId
            ? {
                expenseId: r.expenseId,
                description: d,
                currency: ccy,
                accumulatedAmount: n,
                monthlyAmount: 0,
                isCustomAllocation: true as const,
                ...(customIsPension ? { isPension: true as const } : {}),
              }
            : r,
        ),
      );
    } else {
      onPatch((prev) => [
        ...prev,
        {
          expenseId: newCustomAllocationExpenseId(),
          description: d,
          monthlyAmount: 0,
          accumulatedAmount: n,
          currency: ccy,
          isCustomAllocation: true as const,
          ...(customIsPension ? { isPension: true as const } : {}),
        },
      ]);
    }
    editor.close();
  }

  function submitEditor(e: FormEvent) {
    e.preventDefault();
    if (editingLinkedRow) {
      submitLinkedAllocationEditCore();
      return;
    }
    submitCustomAllocationCore();
  }

  function submitLinkedAllocationEditCore() {
    if (!editingLinkedRow) return;
    const n = parseAmount(linkedAccumStr);
    if (n === null) {
      setLinkedFormError("Accumulated amount must be a valid number.");
      return;
    }
    const linkedExpenseId = editingLinkedRow.expenseId;
    onPatch((prev) =>
      prev.map((r) =>
        r.expenseId === linkedExpenseId
          ? linkedStoredRowPatch(r, n, {
              isIncome: linkedIsIncome,
              isPension: linkedIsPension,
            })
          : r,
      ),
    );
    editor.close();
  }

  const allocationEditor = formOpen ? (
    <AdminEditorPanel
      formId={editorFormId}
      onSubmit={submitEditor}
      submitLabel={editingLinkedRow || editingCustomExpenseId ? "Update record" : "Add record"}
      isSaving={isSaving}
      error={editingLinkedRow ? linkedFormError : customFormError}
    >
          {editingLinkedRow ? (
            <>
              <AdminFieldGrid columns={4}>
                <AdminField label="Description (from expense)" htmlFor="alloc-linked-desc">
                  <input
                    id="alloc-linked-desc"
                    type="text"
                    className="form-control form-control-sm"
                    readOnly
                    value={editingLinkedRow.description}
                  />
                </AdminField>
                <AdminField label="Monthly amount" htmlFor="alloc-linked-monthly">
                  <input
                    id="alloc-linked-monthly"
                    type="text"
                    className="form-control form-control-sm"
                    readOnly
                    value={String(editingLinkedRow.monthlyAmount)}
                  />
                </AdminField>
                <AdminField label="Accumulated amount" htmlFor="alloc-linked-accum">
                  <input
                    id="alloc-linked-accum"
                    type="number"
                    step="0.01"
                    className="form-control form-control-sm"
                    required
                    value={linkedAccumStr}
                    onChange={(ev) => setLinkedAccumStr(ev.target.value)}
                  />
                </AdminField>
                <AdminField label="Currency" htmlFor="alloc-linked-ccy">
                  <input
                    id="alloc-linked-ccy"
                    type="text"
                    className="form-control form-control-sm"
                    readOnly
                    value={editingLinkedRow.currency}
                  />
                </AdminField>
              </AdminFieldGrid>
              <AdminFieldGrid columns={4}>
                <AdminField span={4}>
                  <div className="form-check mb-0">
                    <input
                      id="alloc-linked-income"
                      type="checkbox"
                      className="form-check-input"
                      checked={linkedIsIncome}
                      onChange={(ev) => setLinkedIsIncome(ev.target.checked)}
                    />
                    <label className="form-check-label small" htmlFor="alloc-linked-income">
                      Income (show monthly amount from the expense on the Income tab)
                    </label>
                  </div>
                  <div className="form-check mb-0 mt-2">
                    <input
                      id="alloc-linked-pension"
                      type="checkbox"
                      className="form-check-input"
                      checked={linkedIsPension}
                      onChange={(ev) => setLinkedIsPension(ev.target.checked)}
                    />
                    <label className="form-check-label small" htmlFor="alloc-linked-pension">
                      Pension (show this row on the Pension tab)
                    </label>
                  </div>
                </AdminField>
              </AdminFieldGrid>
            </>
          ) : (
            <>
              <AdminFieldGrid columns={4}>
                <AdminField label="Description" htmlFor="alloc-custom-desc">
                  <input
                    id="alloc-custom-desc"
                    type="text"
                    className="form-control form-control-sm"
                    required
                    value={customDesc}
                    onChange={(ev) => setCustomDesc(ev.target.value)}
                  />
                </AdminField>
                <AdminField label="Accumulated amount" htmlFor="alloc-custom-accum">
                  <input
                    id="alloc-custom-accum"
                    type="number"
                    step="0.01"
                    className="form-control form-control-sm"
                    required
                    value={customAccumStr}
                    onChange={(ev) => setCustomAccumStr(ev.target.value)}
                  />
                </AdminField>
                {customIsIncome ? (
                  <AdminField label="Monthly income" htmlFor="alloc-custom-income-monthly">
                    <input
                      id="alloc-custom-income-monthly"
                      type="number"
                      step="0.01"
                      className="form-control form-control-sm"
                      required={customIsIncome}
                      value={customIncomeMonthlyStr}
                      onChange={(ev) => setCustomIncomeMonthlyStr(ev.target.value)}
                    />
                  </AdminField>
                ) : null}
                <AdminField label="Currency" htmlFor="alloc-custom-ccy">
                  <CurrencySelect
                    id="alloc-custom-ccy"
                    value={customCcy}
                    onChange={(code) =>
                      setCustomCcy(coerceSupportedCurrency(code, GLOBAL_DEFAULT_CURRENCY))
                    }
                  />
                </AdminField>
              </AdminFieldGrid>
              <AdminFieldGrid columns={4}>
                <AdminField span={4}>
                  <div className="form-check mb-0">
                    <input
                      id="alloc-custom-income"
                      type="checkbox"
                      className="form-check-input"
                      checked={customIsIncome}
                      onChange={(ev) => {
                        setCustomIsIncome(ev.target.checked);
                        if (!ev.target.checked) {
                          setCustomIncomeMonthlyStr("");
                        }
                      }}
                    />
                    <label className="form-check-label small" htmlFor="alloc-custom-income">
                      Income (show on Income tab; monthly amount appears on the line above when checked)
                    </label>
                  </div>
                  <div className="form-check mb-0 mt-2">
                    <input
                      id="alloc-custom-pension"
                      type="checkbox"
                      className="form-check-input"
                      checked={customIsPension}
                      onChange={(ev) => setCustomIsPension(ev.target.checked)}
                    />
                    <label className="form-check-label small" htmlFor="alloc-custom-pension">
                      Pension (show this row on the Pension tab)
                    </label>
                  </div>
                </AdminField>
              </AdminFieldGrid>
            </>
          )}
    </AdminEditorPanel>
  ) : null;

  return (
    <div>
      <AdminRecordTable
        label="Allocations"
        filters={
          <AdminFilterBar
            create={<AdminCreateButton label="New allocation" onClick={editor.openCreate} />}
          >
            <AdminFilterField label="Filter" htmlFor="allocations-filter">
              <input
                id="allocations-filter"
                type="search"
                className="form-control form-control-sm"
                placeholder="Filter records…"
                autoComplete="off"
                value={tableFilter}
                onChange={(ev) => setTableFilter(ev.target.value)}
              />
            </AdminFilterField>
          </AdminFilterBar>
        }
      >
        <AdminDataTable
          bare
          columns={tableColumns}
        >
          {editor.expandedId === DRAFT_RECORD_ID ? (
            <AdminExpandableRow colSpan={colSpan} expanded onToggle={editor.openCreate} editor={allocationEditor}>
              <AdminCell column="desc">New allocation</AdminCell>
              <AdminCell column="tags" />
              <AdminCell column="monthly" />
              <AdminCell column="accum" />
              <AdminCell column="last" />
              <AdminCell column="ops" />
            </AdminExpandableRow>
          ) : null}
          {filtered.length ? (
            filtered.map((r) => {
              const monthlyCol = allocationMonthlyColumnDisplay(r);
              return (
              <AdminExpandableRow
                key={r.expenseId}
                colSpan={colSpan}
                expanded={editor.expandedId === r.expenseId}
                onToggle={() => editor.openEdit(r)}
                editor={allocationEditor}
              >
                <AdminCell column="desc" className="small">
                  {r.description}
                  <AdminDataTableCellMeta>
                    {allocationTagsCellLabel(r)}
                    {monthlyCol.kind === "dash" ? null : (
                      <>
                        {" · "}
                        <MoneyAmount amount={monthlyCol.value} currency={monthlyCol.currency} />
                        /mo
                      </>
                    )}
                    {" · "}
                    <MoneyAmount amount={r.accumulatedAmount} currency={r.currency} />
                  </AdminDataTableCellMeta>
                </AdminCell>
                <AdminCell column="tags" className="small text-muted">{allocationTagsCellLabel(r)}</AdminCell>
                <AdminCell column="monthly" className="small text-end">
                  {monthlyCol.kind === "dash" ? (
                    <span className="text-muted">—</span>
                  ) : (
                    <MoneyAmount
                      amount={monthlyCol.value}
                      currency={monthlyCol.currency}
                    />
                  )}
                </AdminCell>
                <AdminCell column="accum" className="small text-end">
                  <MoneyAmount amount={r.accumulatedAmount} currency={r.currency} />
                </AdminCell>
                <AdminCell column="last" className="small">{allocationLastUpdatedDisplay(r.lastUpdated)}</AdminCell>
                <AdminCell column="ops" className="small text-end">
                  <AdminRowActions
                    actions={[
                      {
                        id: "edit",
                        label:
                          r.isCustomAllocation === true
                            ? "Edit custom allocation"
                            : "Edit accumulated amount",
                        iconClassName: "bi bi-pencil",
                        onClick: () => editor.openEdit(r),
                      },
                      {
                        id: "delete",
                        label: "Delete custom allocation",
                        iconClassName: "bi bi-trash",
                        danger: true,
                        hidden: r.isCustomAllocation !== true,
                        onClick: () => editor.requestDelete(r.expenseId),
                      },
                    ]}
                  />
                </AdminCell>
              </AdminExpandableRow>
            );
            })
          ) : (
            <AdminDataTableEmptyRow
              colSpan={colSpan}
              message={
                records.length
                  ? "No records match the filter."
                  : "No allocation rows yet. Tag an expense with Allocate, add derived lines via tagged income and allocation rates on Expenses, or create a custom allocation."
              }
            />
          )}
          {records.length > 0 ? (
            <AdminFxTotalRow
              label="Total (accumulated)"
              labelColumn="desc"
              sheetId="finance-allocations"
              phonePickerId="finance-allocations-total-ccy-phone"
              pickerId="finance-allocations-total-ccy"
              currency={totalDisplayCurrency}
              onCurrencyChange={(code) =>
                setTotalDisplayCurrency(coerceSupportedCurrency(code, GLOBAL_DEFAULT_CURRENCY))
              }
              needsFx={needsFx}
              fxError={fxError}
              fxLoading={fxLoading}
              ratesQuery={ratesQuery}
              cells={[
                { kind: "label" },
                { kind: "empty", column: "tags" },
                { kind: "empty", column: "monthly" },
                { kind: "amount", column: "accum", total: convertedAccumulatedTotal, picker: true },
                { kind: "empty", column: "last" },
                { kind: "empty", column: "ops" },
              ]}
            />
          ) : null}
        </AdminDataTable>
        <ConfirmDialog
          open={editor.pendingDeleteId !== null}
          title="Delete allocation"
          body="Delete this custom allocation?"
          confirmLabel="Delete"
          tone="danger"
          onConfirm={editor.confirmDelete}
          onCancel={editor.cancelDelete}
        />
        <ConfirmDialog
          open={editor.confirmOpen}
          title="Discard unsaved edits?"
          body="This allocation has unsaved changes."
          confirmLabel="Discard"
          cancelLabel="Keep editing"
          tone="danger"
          onConfirm={editor.acceptPending}
          onCancel={editor.cancelPending}
        />
      </AdminRecordTable>
    </div>
  );
}
