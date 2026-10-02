import { type FormEvent, type ReactNode, useMemo, useState } from "react";
import {
  coerceSupportedCurrency,
  GLOBAL_DEFAULT_CURRENCY,
  type CurrencyCode,
} from "../lib/currencies";
import { compareBy } from "../lib/compareBy";
import { formatDateUtc } from "../lib/formatDisplay";
import { parseAmount } from "../lib/formParse";
import { convertAmountToBase } from "../lib/frankfurterRates";
import {
  ASSET_TYPES,
  MAX_PENSION_DESCRIPTION_LEN,
  newStatementLineId,
  type FinanceAllocationRecord,
  type FinancePensionRecord,
  type FinanceSavingsRecord,
  type AssetType,
} from "../lib/financeModel";
import { DRAFT_RECORD_ID } from "../lib/expandedRecord";
import { useRecordEditor } from "../hooks/useRecordEditor";
import { useSortState } from "../hooks/useSortState";
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
  AdminFilterBar,
  AdminFilterField,
  AdminFxTotalRow,
  AdminRecordTable,
  AdminRowActions,
  ConfirmDialog,
  CurrencySelect,
  MoneyAmount,
  StaleValuationBadge,
  TableSortHeaderButton,
} from "./ui";

function pensionLastUpdatedDisplay(lastUpdated: string | undefined): string {
  if (!lastUpdated) {
    return "—";
  }
  return formatDateUtc(`${lastUpdated}T00:00:00.000Z`);
}

/** Pension adds server-managed `lastUpdated`. Savings adds `atype` (asset type) between label and description. */
type MoneyRecordsSortKey = "label" | "atype" | "amt" | "ccy" | "desc" | "lastUpdated";

function compareSavings(
  a: FinanceSavingsRecord,
  b: FinanceSavingsRecord,
  sortKey: MoneyRecordsSortKey,
  sortDir: "asc" | "desc",
): number {
  return compareBy(
    a,
    b,
    sortDir,
    (left, right) => {
      switch (sortKey) {
        case "label":
          return left.deposit.localeCompare(right.deposit, undefined, { sensitivity: "base" });
        case "atype":
          return left.assetType.localeCompare(right.assetType, undefined, { sensitivity: "base" });
        case "amt":
          return left.value === right.value ? 0 : left.value < right.value ? -1 : 1;
        case "ccy":
          return left.currency.localeCompare(right.currency, undefined, { sensitivity: "base" });
        case "desc":
          return left.description.localeCompare(right.description, undefined, { sensitivity: "base" });
        case "lastUpdated":
          return 0;
        default:
          return 0;
      }
    },
    (left, right) => left.id.localeCompare(right.id),
  );
}

type PensionTableFundRow = { readonly kind: "fund"; readonly record: FinancePensionRecord };
type PensionTableAllocationRow = {
  readonly kind: "allocation";
  readonly record: FinanceAllocationRecord;
};
type PensionTableRow = PensionTableFundRow | PensionTableAllocationRow;

function pensionTableFundLabel(row: PensionTableRow): string {
  return row.kind === "fund" ? row.record.fund : "Allocation";
}

function pensionTableValue(row: PensionTableRow): number {
  return row.kind === "fund" ? row.record.value : row.record.accumulatedAmount;
}

function comparePensionTableRows(
  a: PensionTableRow,
  b: PensionTableRow,
  sortKey: MoneyRecordsSortKey,
  sortDir: "asc" | "desc",
): number {
  return compareBy(
    a,
    b,
    sortDir,
    (left, right) => {
      switch (sortKey) {
        case "label":
          return pensionTableFundLabel(left).localeCompare(pensionTableFundLabel(right), undefined, {
            sensitivity: "base",
          });
        case "atype":
          return 0;
        case "amt": {
          const ma = pensionTableValue(left);
          const mb = pensionTableValue(right);
          return ma === mb ? 0 : ma < mb ? -1 : 1;
        }
        case "ccy":
          return left.record.currency.localeCompare(right.record.currency, undefined, {
            sensitivity: "base",
          });
        case "desc":
          return left.record.description.localeCompare(right.record.description, undefined, {
            sensitivity: "base",
          });
        case "lastUpdated": {
          const sa = left.record.lastUpdated ?? "";
          const sb = right.record.lastUpdated ?? "";
          if (!sa && !sb) return 0;
          if (!sa) return 1;
          if (!sb) return -1;
          return sa.localeCompare(sb);
        }
        default:
          return 0;
      }
    },
    (left, right) => {
      const idA = left.kind === "fund" ? left.record.id : left.record.expenseId;
      const idB = right.kind === "fund" ? right.record.id : right.record.expenseId;
      return idA.localeCompare(idB);
    },
  );
}

type MoneyRecord = FinanceSavingsRecord | FinancePensionRecord;

type MoneyFormState = {
  name: string;
  description: string;
  value: string;
  currency: CurrencyCode;
  assetType: AssetType;
};

function emptyMoneyForm(): MoneyFormState {
  return {
    name: "",
    description: "",
    value: "",
    currency: GLOBAL_DEFAULT_CURRENCY,
    assetType: "Fixed",
  };
}

function moneyLineToForm(row: MoneyRecord, variant: "savings" | "pension"): MoneyFormState {
  if (variant === "savings") {
    const record = row as FinanceSavingsRecord;
    return {
      name: record.deposit,
      description: record.description,
      value: String(record.value),
      currency: coerceSupportedCurrency(record.currency, GLOBAL_DEFAULT_CURRENCY),
      assetType: record.assetType,
    };
  }
  const record = row as FinancePensionRecord;
  return {
    name: record.fund,
    description: record.description,
    value: String(record.value),
    currency: coerceSupportedCurrency(record.currency, GLOBAL_DEFAULT_CURRENCY),
    assetType: "Fixed",
  };
}

function clipDescription(value: string): string {
  const trimmed = value.trim();
  return trimmed.length > MAX_PENSION_DESCRIPTION_LEN
    ? trimmed.slice(0, MAX_PENSION_DESCRIPTION_LEN)
    : trimmed;
}

function formToSavingsRecord(
  form: MoneyFormState,
  editingId: string | null,
  labelFormLabel: string,
): { ok: true; record: FinanceSavingsRecord } | { ok: false; error: string } {
  const valueNum = parseAmount(form.value);
  if (!form.name.trim()) return { ok: false, error: `${labelFormLabel} is required.` };
  if (valueNum === null) return { ok: false, error: "Value must be a valid number." };
  const assetType: AssetType = ASSET_TYPES.includes(form.assetType) ? form.assetType : "Fixed";
  return {
    ok: true,
    record: {
      id: editingId ?? newStatementLineId(),
      deposit: form.name.trim(),
      assetType,
      description: clipDescription(form.description),
      value: valueNum,
      currency: coerceSupportedCurrency(form.currency, GLOBAL_DEFAULT_CURRENCY),
    },
  };
}

function formToPensionRecord(
  form: MoneyFormState,
  editingId: string | null,
  labelFormLabel: string,
): { ok: true; record: FinancePensionRecord } | { ok: false; error: string } {
  const valueNum = parseAmount(form.value);
  if (!form.name.trim()) return { ok: false, error: `${labelFormLabel} is required.` };
  if (valueNum === null) return { ok: false, error: "Value must be a valid number." };
  return {
    ok: true,
    record: {
      id: editingId ?? newStatementLineId(),
      fund: form.name.trim(),
      description: clipDescription(form.description),
      value: valueNum,
      currency: coerceSupportedCurrency(form.currency, GLOBAL_DEFAULT_CURRENCY),
    },
  };
}

type SimpleMoneyRecordsPanelProps =
  | {
      variant: "savings";
      records: readonly FinanceSavingsRecord[];
      onPatch: (patch: (prev: readonly FinanceSavingsRecord[]) => FinanceSavingsRecord[]) => void;
      sheetId: string;
      isSaving?: boolean;
      tableSectionTitle: string;
      labelColumnHeader: string;
      labelFormLabel: string;
      labelInputId: string;
      deleteConfirmMessage: string;
      emptyMessage: string;
      /** Table column order: `valueFirst` = Deposit, Value, Currency; `currencyFirst` = Fund, Currency, Value */
      columnOrder: "valueFirst" | "currencyFirst";
    }
  | {
      variant: "pension";
      records: readonly FinancePensionRecord[];
      /** Allocation rows tagged Pension (read-only in this table; edit on Allocations). */
      pensionTaggedAllocationRecords?: readonly FinanceAllocationRecord[];
      onPatch: (patch: (prev: readonly FinancePensionRecord[]) => FinancePensionRecord[]) => void;
      sheetId: string;
      isSaving?: boolean;
      tableSectionTitle: string;
      labelColumnHeader: string;
      labelFormLabel: string;
      labelInputId: string;
      deleteConfirmMessage: string;
      emptyMessage: string;
      columnOrder: "valueFirst" | "currencyFirst";
    };

function SimpleMoneyRecordsPanel(props: SimpleMoneyRecordsPanelProps) {
  const {
    variant,
    records,
    onPatch,
    sheetId,
    tableSectionTitle,
    labelColumnHeader,
    labelFormLabel,
    labelInputId,
    deleteConfirmMessage,
    emptyMessage,
    columnOrder,
    isSaving = false,
  } = props;

  const allocationRecordsForPensionTable =
    props.variant === "pension" ? props.pensionTaggedAllocationRecords : undefined;
  const pensionTaggedAllocationRecords = useMemo(
    () => allocationRecordsForPensionTable ?? [],
    [allocationRecordsForPensionTable],
  );

  const { sortKey, sortDir, onSort, ariaSort, directionFor } = useSortState<MoneyRecordsSortKey>(null);

  const tableColumns = useMemo((): AdminDataTableColumn[] => {

    const labelCol: AdminDataTableColumn = {
      key: "label",
      header: (
        <TableSortHeaderButton
          label={labelColumnHeader}
          isActive={sortKey === "label"}
          direction={directionFor("label")}
          onClick={() => onSort("label")}
        />
      ),
      className: "small",
      thAriaSort: ariaSort("label"),
    };
    const assetTypeCol: AdminDataTableColumn = {
      key: "atype",
      header: (
        <TableSortHeaderButton
          label="Asset type"
          isActive={sortKey === "atype"}
          direction={directionFor("atype")}
          onClick={() => onSort("atype")}
        />
      ),
      className: "small",
      priority: "secondary",
      thAriaSort: ariaSort("atype"),
    };
    const valueCol: AdminDataTableColumn = {
      key: "amt",
      header: (
        <TableSortHeaderButton
          label="Value"
          isActive={sortKey === "amt"}
          direction={directionFor("amt")}
          onClick={() => onSort("amt")}
          align="end"
        />
      ),
      className: "small text-end",
      headerClassName: "small text-end",
      thAriaSort: ariaSort("amt"),
    };
    const opsCol: AdminDataTableColumn = {
      key: "ops",
      header: <span className="visually-hidden">Operations</span>,
      className: "text-end admin-nowrap",
      headerClassName: "text-end",
    };

    const descCol: AdminDataTableColumn = {
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
      priority: "secondary",
      thAriaSort: ariaSort("desc"),
    };

    const lastUpdatedCol: AdminDataTableColumn = {
      key: "lastUpdated",
      header: (
        <TableSortHeaderButton
          label="Last Update"
          isActive={sortKey === "lastUpdated"}
          direction={directionFor("lastUpdated")}
          onClick={() => onSort("lastUpdated")}
        />
      ),
      className: "small admin-nowrap",
      priority: "tertiary",
      thAriaSort: ariaSort("lastUpdated"),
    };

    if (variant === "pension") {
      return [labelCol, descCol, valueCol, lastUpdatedCol, opsCol];
    }
    return [labelCol, assetTypeCol, descCol, valueCol, opsCol];
  }, [
    ariaSort,
    directionFor,
    labelColumnHeader,
    onSort,
    sortKey,
    variant,
  ]);

  const colSpan = tableColumns.length;
  const formId = `${sheetId}-form`;
  const editor = useRecordEditor<MoneyFormState, MoneyRecord>({
    param: sheetId,
    records: records as readonly MoneyRecord[],
    emptyForm: emptyMoneyForm,
    lineToForm: (row) => moneyLineToForm(row, variant),
    onDelete: (id) => {
      if (variant === "savings") {
        const save = onPatch as (
          patch: (prev: readonly FinanceSavingsRecord[]) => FinanceSavingsRecord[],
        ) => void;
        save((prev) => prev.filter((row) => row.id !== id));
      } else {
        const save = onPatch as (
          patch: (prev: readonly FinancePensionRecord[]) => FinancePensionRecord[],
        ) => void;
        save((prev) => prev.filter((row) => row.id !== id));
      }
    },
  });
  const [tableFilter, setTableFilter] = useState("");
  const [totalDisplayCurrency, setTotalDisplayCurrency] = useState<CurrencyCode>(
    GLOBAL_DEFAULT_CURRENCY,
  );

  const filtered = useMemo(() => {
    const q = tableFilter.trim().toLowerCase();
    if (variant === "savings") {
      const recs = records as readonly FinanceSavingsRecord[];
      const list = !q
        ? [...recs]
        : recs.filter((r) => {
            const hay = [r.deposit, r.assetType, r.description, r.currency, String(r.value)]
              .join(" ")
              .toLowerCase();
            return hay.includes(q);
          });
      if (sortKey !== null) {
        list.sort((a, b) => compareSavings(a, b, sortKey, sortDir));
      } else {
        list.sort((a, b) => {
          const byCcy = a.currency.localeCompare(b.currency, undefined, { sensitivity: "base" });
          if (byCcy !== 0) return byCcy;
          return a.deposit.localeCompare(b.deposit, undefined, { sensitivity: "base" });
        });
      }
      return list;
    }
    const fundRecs = records as readonly FinancePensionRecord[];
    const merged: PensionTableRow[] = [
      ...fundRecs.map((record) => ({ kind: "fund" as const, record })),
      ...pensionTaggedAllocationRecords
        .filter((r) => r.isPension === true)
        .map((record) => ({ kind: "allocation" as const, record })),
    ];
    const list = !q
      ? [...merged]
      : merged.filter((row) => {
          if (row.kind === "fund") {
            const r = row.record;
            return [r.fund, r.description, r.currency, String(r.value), r.lastUpdated ?? ""]
              .join(" ")
              .toLowerCase()
              .includes(q);
          }
          const a = row.record;
          return ["allocation", a.description, a.currency, String(a.accumulatedAmount), a.lastUpdated ?? ""]
            .join(" ")
            .toLowerCase()
            .includes(q);
        });
    if (sortKey !== null) {
      list.sort((a, b) => comparePensionTableRows(a, b, sortKey, sortDir));
    } else {
      list.sort((a, b) => {
        const byCcy = a.record.currency.localeCompare(b.record.currency, undefined, {
          sensitivity: "base",
        });
        if (byCcy !== 0) return byCcy;
        return pensionTableFundLabel(a).localeCompare(pensionTableFundLabel(b), undefined, {
          sensitivity: "base",
        });
      });
    }
    return list;
  }, [records, tableFilter, sortKey, sortDir, variant, pensionTaggedAllocationRecords]);

  const recordCurrencies = useMemo(() => {
    if (variant === "pension") {
      return (filtered as readonly PensionTableRow[]).map((row) => row.record.currency);
    }
    return (filtered as readonly FinanceSavingsRecord[]).map((r) => r.currency);
  }, [filtered, variant]);
  const { needsFx, ratesQuery, fxLoading, fxError } = useFrankfurterRatesForTotals(
    totalDisplayCurrency,
    recordCurrencies,
  );

  const convertedTotal = useMemo(() => {
    if (filtered.length === 0) {
      if (variant === "pension") {
        const fundEmpty = (records as readonly FinancePensionRecord[]).length === 0;
        const allocEmpty = !pensionTaggedAllocationRecords.some((r) => r.isPension === true);
        return fundEmpty && allocEmpty ? null : 0;
      }
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
      if (variant === "pension") {
        return (filtered as readonly PensionTableRow[]).reduce(
          (sum, row) =>
            sum +
            convertAmountToBase(
              pensionTableValue(row),
              row.record.currency,
              totalDisplayCurrency,
              map,
            ),
          0,
        );
      }
      const recs = filtered as readonly FinanceSavingsRecord[] | readonly FinancePensionRecord[];
      return recs.reduce(
        (sum, r) => sum + convertAmountToBase(r.value, r.currency, totalDisplayCurrency, map),
        0,
      );
    } catch {
      return null;
    }
  }, [
    filtered,
    records,
    pensionTaggedAllocationRecords,
    variant,
    needsFx,
    ratesQuery.isSuccess,
    ratesQuery.data,
    totalDisplayCurrency,
  ]);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (variant === "savings") {
      const built = formToSavingsRecord(editor.form, editor.editingId, labelFormLabel);
      if (!built.ok) {
        editor.setFormError(built.error);
        return;
      }
      const { record } = built;
      const save = onPatch as (
        patch: (prev: readonly FinanceSavingsRecord[]) => FinanceSavingsRecord[],
      ) => void;
      save((prev) => {
        if (editor.editingId) {
          return prev.map((row) => (row.id === editor.editingId ? record : row));
        }
        return [...prev, record];
      });
    } else {
      const built = formToPensionRecord(editor.form, editor.editingId, labelFormLabel);
      if (!built.ok) {
        editor.setFormError(built.error);
        return;
      }
      const { record } = built;
      const save = onPatch as (
        patch: (prev: readonly FinancePensionRecord[]) => FinancePensionRecord[],
      ) => void;
      save((prev) => {
        if (editor.editingId) {
          return prev.map((row) => (row.id === editor.editingId ? record : row));
        }
        return [...prev, record];
      });
    }
    editor.close();
  }

  const form = editor.form;
  const currencyField = (
    <AdminField label="Currency" htmlFor={`${sheetId}-ccy`}>
      <CurrencySelect
        id={`${sheetId}-ccy`}
        value={form.currency}
        onChange={(code) =>
          editor.setForm((prev) => ({
            ...prev,
            currency: coerceSupportedCurrency(code, GLOBAL_DEFAULT_CURRENCY),
          }))
        }
      />
    </AdminField>
  );
  const valueField = (
    <AdminField label="Value" htmlFor={`${sheetId}-value`}>
      <input
        id={`${sheetId}-value`}
        type="number"
        step="0.01"
        className="form-control form-control-sm"
        required
        value={form.value}
        onChange={(ev) => editor.setForm((prev) => ({ ...prev, value: ev.target.value }))}
      />
    </AdminField>
  );

  const recordEditor = editor.formOpen ? (
    <AdminEditorPanel
      formId={formId}
      onSubmit={submit}
      submitLabel={editor.editingId ? "Update record" : "Add record"}
      isSaving={isSaving}
      error={editor.formError}
    >
      <AdminFieldGrid columns={4}>
        <AdminField label={labelFormLabel} htmlFor={labelInputId}>
          <input
            id={labelInputId}
            type="text"
            className="form-control form-control-sm"
            required
            value={form.name}
            onChange={(ev) => editor.setForm((prev) => ({ ...prev, name: ev.target.value }))}
          />
        </AdminField>
        {variant === "savings" ? (
          <AdminField label="Asset type" htmlFor={`${sheetId}-atype`}>
            <select
              id={`${sheetId}-atype`}
              className="form-select form-select-sm"
              value={form.assetType}
              onChange={(ev) =>
                editor.setForm((prev) => ({ ...prev, assetType: ev.target.value as AssetType }))
              }
            >
              {ASSET_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </AdminField>
        ) : null}
        <AdminField label="Description" htmlFor={`${sheetId}-description`}>
          <input
            id={`${sheetId}-description`}
            type="text"
            className="form-control form-control-sm"
            value={form.description}
            onChange={(ev) => editor.setForm((prev) => ({ ...prev, description: ev.target.value }))}
          />
        </AdminField>
        {columnOrder === "currencyFirst" ? currencyField : null}
        {valueField}
        {columnOrder === "valueFirst" ? currencyField : null}
      </AdminFieldGrid>
    </AdminEditorPanel>
  ) : null;

  const createLabel = variant === "savings" ? "New savings" : "New pension";

  return (
    <div>
      <AdminRecordTable
        label={tableSectionTitle}
        filters={
          <AdminFilterBar create={<AdminCreateButton label={createLabel} onClick={editor.openCreate} />}>
            <AdminFilterField label="Filter" htmlFor={`${sheetId}-filter`}>
              <input
                id={`${sheetId}-filter`}
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
            <AdminExpandableRow colSpan={colSpan} expanded onToggle={editor.openCreate} editor={recordEditor}>
              {tableColumns.map((col) =>
                col.key === "label" ? (
                  <AdminCell key={col.key} column="label">
                    {variant === "savings" ? "New savings" : "New pension"}
                  </AdminCell>
                ) : (
                  <AdminCell key={col.key} column={col.key} />
                ),
              )}
            </AdminExpandableRow>
          ) : null}
          {filtered.length ? (
            variant === "pension" ? (
              (filtered as readonly PensionTableRow[]).map((row) => {
                if (row.kind === "allocation") {
                  const a = row.record;
                  const cells: Record<string, ReactNode> = {
                    label: (
                      <AdminCell key="label" column="label" className="small">
                        Allocation
                        <AdminDataTableCellMeta>
                          {a.description} ·{" "}
                          <MoneyAmount
                            amount={a.accumulatedAmount}
                            currency={a.currency}
                          />
                        </AdminDataTableCellMeta>
                      </AdminCell>
                    ),
                    desc: (
                      <AdminCell key="desc" column="desc" className="small">
                        {a.description}
                      </AdminCell>
                    ),
                    amt: (
                      <AdminCell key="amt" column="amt" className="small text-end">
                        <MoneyAmount amount={a.accumulatedAmount} currency={a.currency} />
                      </AdminCell>
                    ),
                    lastUpdated: (
                      <AdminCell key="lastUpdated" column="lastUpdated" className="small">
                        {pensionLastUpdatedDisplay(a.lastUpdated)}
                      </AdminCell>
                    ),
                    ops: (
                      <AdminCell key="ops" column="ops" className="small text-end text-muted">
                        <span className="visually-hidden">Edit on Allocations</span>—
                      </AdminCell>
                    ),
                  };
                  return (
                    <tr key={`alloc-${a.expenseId}`}>
                      {tableColumns.map((col) => cells[col.key])}
                    </tr>
                  );
                }
                const r = row.record;
                const cells: Record<string, ReactNode> = {
                  label: (
                    <AdminCell key="label" column="label" className="small">
                      {r.fund}
                      <AdminDataTableCellMeta>
                        {r.description} ·{" "}
                        <MoneyAmount amount={r.value} currency={r.currency} />
                      </AdminDataTableCellMeta>
                      <AdminDataTableCellMeta until="tertiary">
                        <StaleValuationBadge lastUpdated={r.lastUpdated} />
                      </AdminDataTableCellMeta>
                    </AdminCell>
                  ),
                  desc: (
                    <AdminCell key="desc" column="desc" className="small">
                      {r.description}
                    </AdminCell>
                  ),
                  amt: (
                    <AdminCell key="amt" column="amt" className="small text-end">
                      <MoneyAmount amount={r.value} currency={r.currency} />
                    </AdminCell>
                  ),
                  lastUpdated: (
                    <AdminCell key="lastUpdated" column="lastUpdated" className="small">
                      {pensionLastUpdatedDisplay(r.lastUpdated)}
                      <StaleValuationBadge lastUpdated={r.lastUpdated} />
                    </AdminCell>
                  ),
                  ops: (
                    <AdminCell key="ops" column="ops" className="small text-end">
                      <AdminRowActions
                        actions={[
                          {
                            id: "edit",
                            label: "Edit record",
                            iconClassName: "bi bi-pencil",
                            onClick: () => editor.openEdit(r),
                          },
                          {
                            id: "delete",
                            label: "Delete record",
                            iconClassName: "bi bi-trash",
                            danger: true,
                            onClick: () => editor.requestDelete(r.id),
                          },
                        ]}
                      />
                    </AdminCell>
                  ),
                };
                return (
                    <AdminExpandableRow
                      key={r.id}
                      colSpan={colSpan}
                      expanded={editor.expandedId === r.id}
                      onToggle={() => editor.openEdit(r)}
                      editor={recordEditor}
                    >
                      {tableColumns.map((col) => cells[col.key])}
                    </AdminExpandableRow>
                  );
              })
            ) : (
              (filtered as readonly FinanceSavingsRecord[]).map((r) => {
                const cells: Record<string, ReactNode> = {
                  label: (
                    <AdminCell key="label" column="label" className="small">
                      {r.deposit}
                      <AdminDataTableCellMeta>
                        {r.assetType} · {r.description} ·{" "}
                        <MoneyAmount amount={r.value} currency={r.currency} />
                      </AdminDataTableCellMeta>
                    </AdminCell>
                  ),
                  atype: (
                    <AdminCell key="atype" column="atype" className="small">
                      {r.assetType}
                    </AdminCell>
                  ),
                  desc: (
                    <AdminCell key="desc" column="desc" className="small">
                      {r.description}
                    </AdminCell>
                  ),
                  amt: (
                    <AdminCell key="amt" column="amt" className="small text-end">
                      <MoneyAmount amount={r.value} currency={r.currency} />
                    </AdminCell>
                  ),
                  ops: (
                    <AdminCell key="ops" column="ops" className="small text-end">
                      <AdminRowActions
                        actions={[
                          {
                            id: "edit",
                            label: "Edit record",
                            iconClassName: "bi bi-pencil",
                            onClick: () => editor.openEdit(r),
                          },
                          {
                            id: "delete",
                            label: "Delete record",
                            iconClassName: "bi bi-trash",
                            danger: true,
                            onClick: () => editor.requestDelete(r.id),
                          },
                        ]}
                      />
                    </AdminCell>
                  ),
                };
                return (
                    <AdminExpandableRow
                      key={r.id}
                      colSpan={colSpan}
                      expanded={editor.expandedId === r.id}
                      onToggle={() => editor.openEdit(r)}
                      editor={recordEditor}
                    >
                      {tableColumns.map((col) => cells[col.key])}
                    </AdminExpandableRow>
                  );
              })
            )
          ) : (
            <AdminDataTableEmptyRow
              colSpan={colSpan}
              message={
                variant === "pension"
                  ? (records as readonly FinancePensionRecord[]).length > 0 ||
                    pensionTaggedAllocationRecords.some((r) => r.isPension === true)
                    ? "No records match the filter."
                    : emptyMessage
                  : records.length
                    ? "No records match the filter."
                    : emptyMessage
              }
            />
          )}
          {((variant === "pension" &&
            ((records as readonly FinancePensionRecord[]).length > 0 ||
              pensionTaggedAllocationRecords.some((r) => r.isPension === true))) ||
          (variant === "savings" && (records as readonly FinanceSavingsRecord[]).length > 0)) ? (
            <AdminFxTotalRow
              labelColumn="label"
              sheetId={sheetId}
              currency={totalDisplayCurrency}
              onCurrencyChange={setTotalDisplayCurrency}
              needsFx={needsFx}
              fxError={fxError}
              fxLoading={fxLoading}
              ratesQuery={ratesQuery}
              cells={tableColumns.map((col) =>
                col.key === "label"
                  ? { kind: "label" as const }
                  : col.key === "amt"
                    ? { kind: "amount" as const, column: "amt", total: convertedTotal, picker: true }
                    : { kind: "empty" as const, column: col.key },
              )}
            />
          ) : null}
        </AdminDataTable>
        <ConfirmDialog
          open={editor.pendingDeleteId !== null}
          title={variant === "savings" ? "Delete savings" : "Delete pension"}
          body={deleteConfirmMessage}
          confirmLabel="Delete"
          tone="danger"
          onConfirm={editor.confirmDelete}
          onCancel={editor.cancelDelete}
        />
        <ConfirmDialog
          open={editor.confirmOpen}
          title="Discard unsaved edits?"
          body="This record has unsaved changes."
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

export function FinanceSavingsPanel(props: {
  readonly records: readonly FinanceSavingsRecord[];
  readonly onPatch: (
    patch: (prev: readonly FinanceSavingsRecord[]) => FinanceSavingsRecord[],
  ) => void;
  readonly isSaving?: boolean;
}) {
  return (
    <SimpleMoneyRecordsPanel
      variant="savings"
      records={props.records}
      onPatch={props.onPatch}
      sheetId="savings"
      isSaving={props.isSaving}
      tableSectionTitle="Savings"
      labelColumnHeader="Deposit"
      labelFormLabel="Deposit"
      labelInputId="savings-deposit"
      deleteConfirmMessage="Delete this savings record?"
      emptyMessage="No savings records yet."
      columnOrder="valueFirst"
    />
  );
}

export function FinancePensionPanel(props: {
  readonly records: readonly FinancePensionRecord[];
  readonly onPatch: (
    patch: (prev: readonly FinancePensionRecord[]) => FinancePensionRecord[],
  ) => void;
  readonly allocationRecords: readonly FinanceAllocationRecord[];
  readonly isSaving?: boolean;
}) {
  return (
    <SimpleMoneyRecordsPanel
      variant="pension"
      records={props.records}
      pensionTaggedAllocationRecords={props.allocationRecords}
      onPatch={props.onPatch}
      sheetId="pension"
      isSaving={props.isSaving}
      tableSectionTitle="Pension"
      labelColumnHeader="Fund"
      labelFormLabel="Fund"
      labelInputId="pension-fund"
      deleteConfirmMessage="Delete this pension record?"
      emptyMessage="No pension records yet."
      columnOrder="valueFirst"
    />
  );
}
