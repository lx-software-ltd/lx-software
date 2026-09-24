import { type FormEvent, type ReactNode, useCallback, useMemo, useState } from "react";
import {
  coerceSupportedCurrency,
  GLOBAL_DEFAULT_CURRENCY,
  type CurrencyCode,
} from "../lib/currencies";
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
  AdminTableTotalCurrency,
  AdminTableTotalLabel,
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
  const dir = sortDir === "asc" ? 1 : -1;
  let cmp = 0;
  switch (sortKey) {
    case "label":
      cmp = a.deposit.localeCompare(b.deposit, undefined, { sensitivity: "base" });
      break;
    case "atype":
      cmp = a.assetType.localeCompare(b.assetType, undefined, { sensitivity: "base" });
      break;
    case "amt": {
      const ma = a.value;
      const mb = b.value;
      cmp = ma === mb ? 0 : ma < mb ? -1 : 1;
      break;
    }
    case "ccy":
      cmp = a.currency.localeCompare(b.currency, undefined, { sensitivity: "base" });
      break;
    case "desc":
      cmp = a.description.localeCompare(b.description, undefined, { sensitivity: "base" });
      break;
    case "lastUpdated":
      cmp = 0;
      break;
    default:
      break;
  }
  if (cmp !== 0) return dir * cmp;
  return a.id.localeCompare(b.id);
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
  const dir = sortDir === "asc" ? 1 : -1;
  let cmp = 0;
  switch (sortKey) {
    case "label":
      cmp = pensionTableFundLabel(a).localeCompare(pensionTableFundLabel(b), undefined, {
        sensitivity: "base",
      });
      break;
    case "atype":
      cmp = 0;
      break;
    case "amt": {
      const ma = pensionTableValue(a);
      const mb = pensionTableValue(b);
      cmp = ma === mb ? 0 : ma < mb ? -1 : 1;
      break;
    }
    case "ccy":
      cmp = a.record.currency.localeCompare(b.record.currency, undefined, { sensitivity: "base" });
      break;
    case "desc":
      cmp = a.record.description.localeCompare(b.record.description, undefined, {
        sensitivity: "base",
      });
      break;
    case "lastUpdated": {
      const sa = a.record.lastUpdated ?? "";
      const sb = b.record.lastUpdated ?? "";
      if (!sa && !sb) {
        cmp = 0;
      } else if (!sa) {
        cmp = 1;
      } else if (!sb) {
        cmp = -1;
      } else {
        cmp = sa.localeCompare(sb);
      }
      break;
    }
    default:
      break;
  }
  if (cmp !== 0) return dir * cmp;
  const idA = a.kind === "fund" ? a.record.id : a.record.expenseId;
  const idB = b.kind === "fund" ? b.record.id : b.record.expenseId;
  return idA.localeCompare(idB);
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

  /** Savings editor: one row on large screens, each control ~1/6 width (Bootstrap 12-col → col per row-cols-6). */
  const savingsSingleRowGrid = variant === "savings";

  const [sortKey, setSortKey] = useState<MoneyRecordsSortKey | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const onSort = useCallback((key: MoneyRecordsSortKey) => {
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
      key: MoneyRecordsSortKey,
    ): "ascending" | "descending" | "none" | "other" | undefined => {
      if (!manualSort) return undefined;
      if (sortKey === key) return sortDir === "asc" ? "ascending" : "descending";
      return "none";
    };
    const dirFor = (key: MoneyRecordsSortKey): "asc" | "desc" | null =>
      sortKey === key ? sortDir : null;

    const labelCol: AdminDataTableColumn = {
      key: "label",
      header: (
        <TableSortHeaderButton
          label={labelColumnHeader}
          isActive={sortKey === "label"}
          direction={dirFor("label")}
          onClick={() => onSort("label")}
        />
      ),
      className: "small",
      thAriaSort: thAria("label"),
    };
    const assetTypeCol: AdminDataTableColumn = {
      key: "atype",
      header: (
        <TableSortHeaderButton
          label="Asset type"
          isActive={sortKey === "atype"}
          direction={dirFor("atype")}
          onClick={() => onSort("atype")}
        />
      ),
      className: "small",
      priority: "secondary",
      thAriaSort: thAria("atype"),
    };
    const valueCol: AdminDataTableColumn = {
      key: "amt",
      header: (
        <TableSortHeaderButton
          label="Value"
          isActive={sortKey === "amt"}
          direction={dirFor("amt")}
          onClick={() => onSort("amt")}
          align="end"
        />
      ),
      className: "small text-end",
      headerClassName: "small text-end",
      thAriaSort: thAria("amt"),
    };
    const ccyCol: AdminDataTableColumn = {
      key: "ccy",
      header: (
        <TableSortHeaderButton
          label="Currency"
          isActive={sortKey === "ccy"}
          direction={dirFor("ccy")}
          onClick={() => onSort("ccy")}
        />
      ),
      className: "small",
      priority: "secondary",
      thAriaSort: thAria("ccy"),
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
          direction={dirFor("desc")}
          onClick={() => onSort("desc")}
        />
      ),
      className: "small",
      priority: "secondary",
      thAriaSort: thAria("desc"),
    };

    const lastUpdatedCol: AdminDataTableColumn = {
      key: "lastUpdated",
      header: (
        <TableSortHeaderButton
          label="Last Update"
          isActive={sortKey === "lastUpdated"}
          direction={dirFor("lastUpdated")}
          onClick={() => onSort("lastUpdated")}
        />
      ),
      className: "small admin-nowrap",
      priority: "tertiary",
      thAriaSort: thAria("lastUpdated"),
    };

    if (variant === "pension") {
      return columnOrder === "valueFirst"
        ? [labelCol, descCol, valueCol, ccyCol, lastUpdatedCol, opsCol]
        : [labelCol, descCol, ccyCol, valueCol, lastUpdatedCol, opsCol];
    }
    return columnOrder === "valueFirst"
      ? [labelCol, assetTypeCol, descCol, valueCol, ccyCol, opsCol]
      : [labelCol, assetTypeCol, descCol, ccyCol, valueCol, opsCol];
  }, [
    columnOrder,
    labelColumnHeader,
    onSort,
    sortDir,
    sortKey,
    variant,
  ]);

  const colSpan = tableColumns.length;
  const formId = `${sheetId}-form`;
  const expanded = useExpandedRecord(sheetId);
  const editingId =
    expanded.expandedId && expanded.expandedId !== DRAFT_RECORD_ID
      ? expanded.expandedId
      : null;
  const formOpen = expanded.expandedId !== null;
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [nameInput, setNameInput] = useState("");
  const [descriptionInput, setDescriptionInput] = useState("");
  const [valueStr, setValueStr] = useState("");
  const [formCurrency, setFormCurrency] = useState(GLOBAL_DEFAULT_CURRENCY);
  const [assetTypeInput, setAssetTypeInput] = useState<AssetType>("Fixed");
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

  function resetFields() {
    setFormError(null);
    setNameInput("");
    setDescriptionInput("");
    setValueStr("");
    setFormCurrency(GLOBAL_DEFAULT_CURRENCY);
    setAssetTypeInput("Fixed");
  }

  function applyRecord(row: FinanceSavingsRecord | FinancePensionRecord) {
    setFormError(null);
    if (variant === "savings") {
      const r = row as FinanceSavingsRecord;
      setNameInput(r.deposit);
      setAssetTypeInput(r.assetType);
      setDescriptionInput(r.description);
      setValueStr(String(r.value));
      setFormCurrency(coerceSupportedCurrency(r.currency, GLOBAL_DEFAULT_CURRENCY));
    } else {
      const r = row as FinancePensionRecord;
      setNameInput(r.fund);
      setDescriptionInput(r.description);
      setValueStr(String(r.value));
      setFormCurrency(coerceSupportedCurrency(r.currency, GLOBAL_DEFAULT_CURRENCY));
    }
  }

  function recordDirty(): boolean {
    if (!formOpen) return false;
    if (!editingId) {
      return nameInput.trim() !== "" || valueStr.trim() !== "" || descriptionInput.trim() !== "";
    }
    if (variant === "savings") {
      const row = (records as readonly FinanceSavingsRecord[]).find((record) => record.id === editingId);
      if (!row) return false;
      return (
        nameInput !== row.deposit ||
        descriptionInput !== row.description ||
        valueStr !== String(row.value) ||
        formCurrency !== coerceSupportedCurrency(row.currency, GLOBAL_DEFAULT_CURRENCY) ||
        assetTypeInput !== row.assetType
      );
    }
    const row = (records as readonly FinancePensionRecord[]).find((record) => record.id === editingId);
    if (!row) return false;
    return (
      nameInput !== row.fund ||
      descriptionInput !== row.description ||
      valueStr !== String(row.value) ||
      formCurrency !== coerceSupportedCurrency(row.currency, GLOBAL_DEFAULT_CURRENCY)
    );
  }

  const editingMoney = editingId
    ? variant === "savings"
      ? ((records as readonly FinanceSavingsRecord[]).find((record) => record.id === editingId) ?? null)
      : ((records as readonly FinancePensionRecord[]).find((record) => record.id === editingId) ?? null)
    : null;
  useHydrateExpandedRecord({
    expandedId: expanded.expandedId,
    recordsReady: true,
    record: editingMoney,
    apply: (row) => applyRecord(row),
    onMissing: () => expanded.request(null, false),
  });

  function openEdit(row: FinanceSavingsRecord | FinancePensionRecord) {
    expanded.toggle(row.id, recordDirty(), () => applyRecord(row), resetFields);
  }

  function openCreate() {
    if (expanded.expandedId === DRAFT_RECORD_ID) {
      expanded.request(null, recordDirty(), resetFields);
      return;
    }
    expanded.request(DRAFT_RECORD_ID, recordDirty(), resetFields);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const valueNum = parseAmount(valueStr);
    if (!nameInput.trim()) {
      setFormError(`${labelFormLabel} is required.`);
      return;
    }
    if (valueNum === null) {
      setFormError("Value must be a valid number.");
      return;
    }
    const currency = coerceSupportedCurrency(formCurrency, GLOBAL_DEFAULT_CURRENCY);
    const id = editingId ?? newStatementLineId();

    if (variant === "savings") {
      const assetType: AssetType = ASSET_TYPES.includes(assetTypeInput)
        ? assetTypeInput
        : "Fixed";
      const descTrimmed = descriptionInput.trim();
      const row: FinanceSavingsRecord = {
        id,
        deposit: nameInput.trim(),
        assetType,
        description:
          descTrimmed.length > MAX_PENSION_DESCRIPTION_LEN
            ? descTrimmed.slice(0, MAX_PENSION_DESCRIPTION_LEN)
            : descTrimmed,
        value: valueNum,
        currency,
      };
      const save = onPatch as (
        patch: (prev: readonly FinanceSavingsRecord[]) => FinanceSavingsRecord[],
      ) => void;
      save((prev) => {
        if (editingId) {
          return prev.map((r) => (r.id === editingId ? row : r));
        }
        return [...prev, row];
      });
    } else {
      const descTrimmed = descriptionInput.trim();
      const row: FinancePensionRecord = {
        id,
        fund: nameInput.trim(),
        description:
          descTrimmed.length > MAX_PENSION_DESCRIPTION_LEN
            ? descTrimmed.slice(0, MAX_PENSION_DESCRIPTION_LEN)
            : descTrimmed,
        value: valueNum,
        currency,
      };
      const save = onPatch as (
        patch: (prev: readonly FinancePensionRecord[]) => FinancePensionRecord[],
      ) => void;
      save((prev) => {
        if (editingId) {
          return prev.map((r) => (r.id === editingId ? row : r));
        }
        return [...prev, row];
      });
    }

    resetFields();
    expanded.request(null, false);
  }

  function deleteRow(id: string) {
    if (variant === "savings") {
      const save = onPatch as (
        patch: (prev: readonly FinanceSavingsRecord[]) => FinanceSavingsRecord[],
      ) => void;
      save((prev) => prev.filter((r) => r.id !== id));
    } else {
      const save = onPatch as (
        patch: (prev: readonly FinancePensionRecord[]) => FinancePensionRecord[],
      ) => void;
      save((prev) => prev.filter((r) => r.id !== id));
    }
    if (editingId === id) {
      resetFields();
      expanded.request(null, false);
    }
    setPendingDeleteId(null);
  }

  const recordEditor = formOpen ? (
    <AdminEditorPanel
      formId={formId}
      onSubmit={submit}
      submitLabel={editingId ? "Update record" : "Add record"}
      isSaving={isSaving}
      error={formError}
    >
          <div
            className={
              savingsSingleRowGrid ? "row g-3 row-cols-1 row-cols-lg-6" : "row g-3"
            }
          >
            <div className={savingsSingleRowGrid ? "col" : "col-md-3"}>
              <label className="form-label small" htmlFor={labelInputId}>
                {labelFormLabel}
              </label>
              <input
                id={labelInputId}
                type="text"
                className="form-control form-control-sm"
                required
                value={nameInput}
                onChange={(ev) => setNameInput(ev.target.value)}
              />
            </div>
            {variant === "savings" ? (
              <div className="col">
                <label className="form-label small" htmlFor={`${sheetId}-atype`}>
                  Asset type
                </label>
                <select
                  id={`${sheetId}-atype`}
                  className="form-select form-select-sm"
                  value={assetTypeInput}
                  onChange={(ev) =>
                    setAssetTypeInput(ev.target.value as AssetType)
                  }
                >
                  {ASSET_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className={savingsSingleRowGrid ? "col" : "col-md-3"}>
              <label className="form-label small" htmlFor={`${sheetId}-description`}>
                Description
              </label>
              <input
                id={`${sheetId}-description`}
                type="text"
                className="form-control form-control-sm"
                value={descriptionInput}
                onChange={(ev) => setDescriptionInput(ev.target.value)}
              />
            </div>
            {columnOrder === "currencyFirst" ? (
              <div className={savingsSingleRowGrid ? "col" : "col-md-3"}>
                <label className="form-label small" htmlFor={`${sheetId}-ccy`}>
                  Currency
                </label>
                <CurrencySelect
                  id={`${sheetId}-ccy`}
                  value={formCurrency}
                  onChange={(code) =>
                    setFormCurrency(coerceSupportedCurrency(code, GLOBAL_DEFAULT_CURRENCY))
                  }
                />
              </div>
            ) : null}
            <div className={savingsSingleRowGrid ? "col" : "col-md-3"}>
              <label className="form-label small" htmlFor={`${sheetId}-value`}>
                Value
              </label>
              <input
                id={`${sheetId}-value`}
                type="number"
                step="0.01"
                className="form-control form-control-sm"
                required
                value={valueStr}
                onChange={(ev) => setValueStr(ev.target.value)}
              />
            </div>
            {columnOrder === "valueFirst" ? (
              <div className={savingsSingleRowGrid ? "col" : "col-md-3"}>
                <label className="form-label small" htmlFor={`${sheetId}-ccy`}>
                  Currency
                </label>
                <CurrencySelect
                  id={`${sheetId}-ccy`}
                  value={formCurrency}
                  onChange={(code) =>
                    setFormCurrency(coerceSupportedCurrency(code, GLOBAL_DEFAULT_CURRENCY))
                  }
                />
              </div>
            ) : null}
          </div>
    </AdminEditorPanel>
  ) : null;

  const createLabel = variant === "savings" ? "New savings" : "New pension";

  return (
    <div>
      <AdminRecordTable
        label={tableSectionTitle}
        filters={
          <AdminFilterBar create={<AdminCreateButton label={createLabel} onClick={openCreate} />}>
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
          {expanded.expandedId === DRAFT_RECORD_ID ? (
            <AdminExpandableRow colSpan={colSpan} expanded onToggle={openCreate} editor={recordEditor}>
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
                          {a.description} · {a.currency} ·{" "}
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
                        <MoneyAmount amount={a.accumulatedAmount} currency={a.currency} amountOnly />
                      </AdminCell>
                    ),
                    ccy: (
                      <AdminCell key="ccy" column="ccy" className="small">
                        {a.currency}
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
                        {r.description} · {r.currency} ·{" "}
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
                      <MoneyAmount amount={r.value} currency={r.currency} amountOnly />
                    </AdminCell>
                  ),
                  ccy: (
                    <AdminCell key="ccy" column="ccy" className="small">
                      {r.currency}
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
                            onClick: () => openEdit(r),
                          },
                          {
                            id: "delete",
                            label: "Delete record",
                            iconClassName: "bi bi-trash",
                            danger: true,
                            onClick: () => setPendingDeleteId(r.id),
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
                      expanded={expanded.expandedId === r.id}
                      onToggle={() => openEdit(r)}
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
                        {r.assetType} · {r.description} · {r.currency} ·{" "}
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
                      <MoneyAmount amount={r.value} currency={r.currency} amountOnly />
                    </AdminCell>
                  ),
                  ccy: (
                    <AdminCell key="ccy" column="ccy" className="small">
                      {r.currency}
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
                            onClick: () => openEdit(r),
                          },
                          {
                            id: "delete",
                            label: "Delete record",
                            iconClassName: "bi bi-trash",
                            danger: true,
                            onClick: () => setPendingDeleteId(r.id),
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
                      expanded={expanded.expandedId === r.id}
                      onToggle={() => openEdit(r)}
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
            <tr className="table-group-divider table-secondary fw-semibold">
              {tableColumns.map((col) => {
                if (col.key === "label") {
                  return (
                    <AdminCell key={col.key} column="label" className="small">
                      <AdminTableTotalLabel
                        needsFx={needsFx}
                        fxError={fxError}
                        fxLoading={fxLoading}
                        ratesQuery={ratesQuery}
                        phoneValue={
                          <>
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
                              id={`${sheetId}-total-ccy-phone`}
                              value={totalDisplayCurrency}
                              onChange={setTotalDisplayCurrency}
                              disabled={fxLoading}
                            />
                          </>
                        }
                      />
                    </AdminCell>
                  );
                }
                if (col.key === "amt") {
                  return (
                    <AdminCell key={col.key} column="amt" className="small text-end">
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
                        id={`${sheetId}-total-ccy`}
                        value={totalDisplayCurrency}
                        onChange={setTotalDisplayCurrency}
                        disabled={fxLoading}
                      />
                    </AdminCell>
                  );
                }
                return <AdminCell key={col.key} column={col.key} className="small" />;
              })}
            </tr>
          ) : null}
        </AdminDataTable>
        <ConfirmDialog
          open={pendingDeleteId !== null}
          title={variant === "savings" ? "Delete savings" : "Delete pension"}
          body={deleteConfirmMessage}
          confirmLabel="Delete"
          tone="danger"
          onConfirm={() => {
            if (pendingDeleteId) deleteRow(pendingDeleteId);
          }}
          onCancel={() => setPendingDeleteId(null)}
        />
        <ConfirmDialog
          open={expanded.confirmOpen}
          title="Discard unsaved edits?"
          body="This record has unsaved changes."
          confirmLabel="Discard"
          cancelLabel="Keep editing"
          tone="danger"
          onConfirm={expanded.acceptPending}
          onCancel={expanded.cancelPending}
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
