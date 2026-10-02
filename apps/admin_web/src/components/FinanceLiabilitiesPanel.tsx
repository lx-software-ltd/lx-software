import { type FormEvent, useMemo, useState } from "react";
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
  FINANCE_LIABILITY_TYPES,
  newStatementLineId,
  type FinanceLiabilityRecord,
  type FinanceLiabilityType,
  type HouseKey,
} from "../lib/financeModel";
import { houseDisplayLabel } from "../lib/houses";
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

function liabilityLastUpdatedDisplay(lastUpdated: string | undefined): string {
  if (!lastUpdated) {
    return "—";
  }
  return formatDateUtc(`${lastUpdated}T00:00:00.000Z`);
}

type LiabilitiesSortKey = "desc" | "ltype" | "amt" | "rate" | "ccy" | "house" | "lastUpdated";

type LiabilityFormState = {
  description: string;
  liabilityType: FinanceLiabilityType;
  balance: string;
  rate: string;
  relatedHouse: HouseKey | "";
  currency: CurrencyCode;
};

function emptyLiabilityForm(): LiabilityFormState {
  return {
    description: "",
    liabilityType: "Mortgage",
    balance: "",
    rate: "",
    relatedHouse: "",
    currency: GLOBAL_DEFAULT_CURRENCY,
  };
}

function lineToForm(row: FinanceLiabilityRecord): LiabilityFormState {
  return {
    description: row.description,
    liabilityType: row.liabilityType,
    balance: String(row.outstandingBalance),
    rate: row.interestRatePercent !== undefined ? String(row.interestRatePercent) : "",
    relatedHouse: row.relatedHouse ?? "",
    currency: coerceSupportedCurrency(row.currency, GLOBAL_DEFAULT_CURRENCY),
  };
}

function formToRecord(
  form: LiabilityFormState,
  editingId: string | null,
): { ok: true; record: FinanceLiabilityRecord } | { ok: false; error: string } {
  const description = form.description.trim();
  if (!description) {
    return { ok: false, error: "Description is required." };
  }
  const balanceNum = parseAmount(form.balance);
  if (balanceNum === null || balanceNum < 0) {
    return { ok: false, error: "Outstanding balance must be a number ≥ 0." };
  }
  let interestRatePercent: number | undefined;
  if (form.rate.trim()) {
    const rateNum = parseAmount(form.rate);
    if (rateNum === null || rateNum < 0 || rateNum > 100) {
      return { ok: false, error: "Interest rate must be a number between 0 and 100." };
    }
    interestRatePercent = rateNum;
  }
  const currency = coerceSupportedCurrency(form.currency, GLOBAL_DEFAULT_CURRENCY);
  return {
    ok: true,
    record: {
      id: editingId ?? newStatementLineId(),
      description,
      liabilityType: form.liabilityType,
      outstandingBalance: balanceNum,
      currency,
      ...(interestRatePercent !== undefined ? { interestRatePercent } : {}),
      ...(form.relatedHouse ? { relatedHouse: form.relatedHouse } : {}),
    },
  };
}

function compareLiabilities(
  a: FinanceLiabilityRecord,
  b: FinanceLiabilityRecord,
  sortKey: LiabilitiesSortKey,
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
        case "ltype":
          return left.liabilityType.localeCompare(right.liabilityType, undefined, { sensitivity: "base" });
        case "amt":
          return left.outstandingBalance === right.outstandingBalance
            ? 0
            : left.outstandingBalance < right.outstandingBalance
              ? -1
              : 1;
        case "rate": {
          const ra = left.interestRatePercent ?? -1;
          const rb = right.interestRatePercent ?? -1;
          return ra === rb ? 0 : ra < rb ? -1 : 1;
        }
        case "ccy":
          return left.currency.localeCompare(right.currency, undefined, { sensitivity: "base" });
        case "house":
          return (left.relatedHouse ?? "").localeCompare(right.relatedHouse ?? "", undefined, {
            sensitivity: "base",
          });
        case "lastUpdated": {
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
    (left, right) => left.id.localeCompare(right.id),
  );
}

export function FinanceLiabilitiesPanel(props: {
  readonly records: readonly FinanceLiabilityRecord[];
  readonly onPatch: (
    patch: (prev: readonly FinanceLiabilityRecord[]) => FinanceLiabilityRecord[],
  ) => void;
  readonly isSaving?: boolean;
  readonly relatedHouseOptions: ReadonlyArray<{
    readonly value: HouseKey;
    readonly label: string;
  }>;
}) {
  const { records, onPatch, relatedHouseOptions, isSaving = false } = props;
  const sheetId = "liabilities";
  const formId = `${sheetId}-form`;
  const { sortKey, sortDir, onSort, ariaSort, directionFor } = useSortState<LiabilitiesSortKey>("ltype");
  const [tableFilter, setTableFilter] = useState("");
  const [totalDisplayCurrency, setTotalDisplayCurrency] = useState<CurrencyCode>(
    GLOBAL_DEFAULT_CURRENCY,
  );

  const editor = useRecordEditor<LiabilityFormState, FinanceLiabilityRecord>({
    param: "liability",
    records,
    emptyForm: emptyLiabilityForm,
    lineToForm,
    onDelete: (id) => {
      onPatch((prev) => prev.filter((row) => row.id !== id));
    },
  });

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
        key: "ltype",
        header: (
          <TableSortHeaderButton
            label="Liability Type"
            isActive={sortKey === "ltype"}
            direction={directionFor("ltype")}
            onClick={() => onSort("ltype")}
          />
        ),
        className: "small",
        priority: "secondary",
        thAriaSort: ariaSort("ltype"),
      },
      {
        key: "amt",
        header: (
          <TableSortHeaderButton
            label="Outstanding Balance"
            isActive={sortKey === "amt"}
            direction={directionFor("amt")}
            onClick={() => onSort("amt")}
          />
        ),
        className: "small text-end",
        headerClassName: "text-end",
        thAriaSort: ariaSort("amt"),
      },
      {
        key: "rate",
        header: (
          <TableSortHeaderButton
            label="Interest Rate"
            isActive={sortKey === "rate"}
            direction={directionFor("rate")}
            onClick={() => onSort("rate")}
          />
        ),
        className: "small text-end",
        headerClassName: "text-end",
        priority: "tertiary",
        thAriaSort: ariaSort("rate"),
      },
      {
        key: "house",
        header: (
          <TableSortHeaderButton
            label="Related Property"
            isActive={sortKey === "house"}
            direction={directionFor("house")}
            onClick={() => onSort("house")}
          />
        ),
        className: "small",
        priority: "secondary",
        thAriaSort: ariaSort("house"),
      },
      {
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

  const filtered = useMemo(() => {
    const q = tableFilter.trim().toLowerCase();
    const list = !q
      ? [...records]
      : records.filter((r) => {
          const hay = [
            r.description,
            r.liabilityType,
            r.currency,
            String(r.outstandingBalance),
            r.interestRatePercent !== undefined ? String(r.interestRatePercent) : "",
            houseDisplayLabel(r.relatedHouse),
            r.lastUpdated ?? "",
          ]
            .join(" ")
            .toLowerCase();
          return hay.includes(q);
        });
    if (sortKey !== null) {
      list.sort((a, b) => compareLiabilities(a, b, sortKey, sortDir));
    } else {
      list.sort((a, b) => {
        const byType = a.liabilityType.localeCompare(b.liabilityType, undefined, {
          sensitivity: "base",
        });
        if (byType !== 0) return byType;
        return a.description.localeCompare(b.description, undefined, { sensitivity: "base" });
      });
    }
    return list;
  }, [records, tableFilter, sortKey, sortDir]);

  const recordCurrencies = useMemo(() => filtered.map((r) => r.currency), [filtered]);
  const { needsFx, ratesQuery, fxLoading, fxError } = useFrankfurterRatesForTotals(
    totalDisplayCurrency,
    recordCurrencies,
  );

  const convertedTotal = useMemo(() => {
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
          sum + convertAmountToBase(r.outstandingBalance, r.currency, totalDisplayCurrency, map),
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

  function submit(e: FormEvent) {
    e.preventDefault();
    const built = formToRecord(editor.form, editor.editingId);
    if (!built.ok) {
      editor.setFormError(built.error);
      return;
    }
    const { record } = built;
    onPatch((prev) => {
      if (editor.editingId) {
        return prev.map((r) => (r.id === editor.editingId ? record : r));
      }
      return [...prev, record];
    });
    editor.close();
  }

  const form = editor.form;
  const liabilityEditor = editor.formOpen ? (
    <AdminEditorPanel
      formId={formId}
      onSubmit={submit}
      submitLabel={editor.editingId ? "Update record" : "Add record"}
      isSaving={isSaving}
      error={editor.formError}
    >
      <AdminFieldGrid columns={4}>
        <AdminField label="Description" htmlFor={`${sheetId}-description`}>
          <input
            id={`${sheetId}-description`}
            type="text"
            className="form-control form-control-sm"
            required
            value={form.description}
            onChange={(ev) => editor.setForm((prev) => ({ ...prev, description: ev.target.value }))}
            placeholder="e.g. lender and product"
            autoComplete="off"
          />
        </AdminField>
        <AdminField label="Liability Type" htmlFor={`${sheetId}-liability-type`}>
          <select
            id={`${sheetId}-liability-type`}
            className="form-select form-select-sm"
            value={form.liabilityType}
            onChange={(ev) =>
              editor.setForm((prev) => ({
                ...prev,
                liabilityType: ev.target.value as FinanceLiabilityType,
              }))
            }
          >
            {FINANCE_LIABILITY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </AdminField>
        <AdminField label="Outstanding Balance" htmlFor={`${sheetId}-balance`}>
          <input
            id={`${sheetId}-balance`}
            type="number"
            step="0.01"
            min={0}
            className="form-control form-control-sm"
            required
            value={form.balance}
            onChange={(ev) => editor.setForm((prev) => ({ ...prev, balance: ev.target.value }))}
          />
        </AdminField>
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
        <AdminField label="Interest Rate %" htmlFor={`${sheetId}-rate`}>
          <input
            id={`${sheetId}-rate`}
            type="number"
            step="0.01"
            min={0}
            max={100}
            className="form-control form-control-sm"
            value={form.rate}
            onChange={(ev) => editor.setForm((prev) => ({ ...prev, rate: ev.target.value }))}
            placeholder="optional"
          />
        </AdminField>
        <AdminField label="Related Property" htmlFor={`${sheetId}-related-house`}>
          <select
            id={`${sheetId}-related-house`}
            className="form-select form-select-sm"
            value={form.relatedHouse}
            onChange={(ev) =>
              editor.setForm((prev) => ({ ...prev, relatedHouse: ev.target.value as HouseKey | "" }))
            }
          >
            <option value="">—</option>
            {relatedHouseOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </AdminField>
      </AdminFieldGrid>
    </AdminEditorPanel>
  ) : null;

  return (
    <div>
      <AdminRecordTable
        label="Liabilities"
        filters={
          <AdminFilterBar create={<AdminCreateButton label="New liability" onClick={editor.openCreate} />}>
            <AdminFilterField label="Filter" htmlFor="liabilities-filter">
              <input id="liabilities-filter" type="search" className="form-control form-control-sm" placeholder="Filter records…" autoComplete="off" value={tableFilter} onChange={(ev) => setTableFilter(ev.target.value)} />
            </AdminFilterField>
          </AdminFilterBar>
        }
      >
        <AdminDataTable
          bare
          columns={tableColumns}
        >
          {editor.expandedId === DRAFT_RECORD_ID ? (
            <AdminExpandableRow colSpan={colSpan} expanded onToggle={editor.openCreate} editor={liabilityEditor}>
              <AdminCell column="desc">New liability</AdminCell>
              <AdminCell column="ltype" />
              <AdminCell column="amt" />
              <AdminCell column="rate" />
              <AdminCell column="house" />
              <AdminCell column="lastUpdated" />
              <AdminCell column="ops" />
            </AdminExpandableRow>
          ) : null}
          {filtered.length ? (
            filtered.map((r) => (
              <AdminExpandableRow
                key={r.id}
                colSpan={colSpan}
                expanded={editor.expandedId === r.id}
                onToggle={() => editor.openEdit(r)}
                editor={liabilityEditor}
              >
                <AdminCell column="desc" className="small">
                  {r.description}
                  <AdminDataTableCellMeta>
                    {r.liabilityType} · {r.currency}
                    {r.relatedHouse ? ` · ${houseDisplayLabel(r.relatedHouse)}` : ""}
                    {" · "}
                    <MoneyAmount amount={r.outstandingBalance} currency={r.currency} />
                  </AdminDataTableCellMeta>
                  <AdminDataTableCellMeta until="tertiary">
                    <StaleValuationBadge lastUpdated={r.lastUpdated} />
                  </AdminDataTableCellMeta>
                </AdminCell>
                <AdminCell column="ltype" className="small">{r.liabilityType}</AdminCell>
                <AdminCell column="amt" className="small text-end">
                  <MoneyAmount amount={r.outstandingBalance} currency={r.currency} codePrefix />
                </AdminCell>
                <AdminCell column="rate" className="small text-end">
                  {r.interestRatePercent !== undefined ? `${r.interestRatePercent}%` : "—"}
                </AdminCell>
                <AdminCell column="house" className="small">{houseDisplayLabel(r.relatedHouse)}</AdminCell>
                <AdminCell column="lastUpdated" className="small">
                  {liabilityLastUpdatedDisplay(r.lastUpdated)}
                  <StaleValuationBadge lastUpdated={r.lastUpdated} />
                </AdminCell>
                <AdminCell column="ops" className="small text-end">
                  <AdminRowActions
                    actions={[
                      { id: "edit", label: "Edit record", iconClassName: "bi bi-pencil", onClick: () => editor.openEdit(r) },
                      { id: "delete", label: "Delete record", iconClassName: "bi bi-trash", danger: true, onClick: () => editor.requestDelete(r.id) },
                    ]}
                  />
                </AdminCell>
              </AdminExpandableRow>
            ))
          ) : (
            <AdminDataTableEmptyRow
              colSpan={colSpan}
              message={
                records.length ? "No records match the filter." : "No liability records yet."
              }
            />
          )}
          {records.length > 0 ? (
            <AdminFxTotalRow
              label="Total owed"
              labelColumn="desc"
              sheetId={sheetId}
              currency={totalDisplayCurrency}
              onCurrencyChange={setTotalDisplayCurrency}
              needsFx={needsFx}
              fxError={fxError}
              fxLoading={fxLoading}
              ratesQuery={ratesQuery}
              cells={[
                { kind: "label" },
                { kind: "empty", column: "ltype" },
                { kind: "amount", column: "amt", total: convertedTotal, picker: true },
                { kind: "empty", column: "rate" },
                { kind: "empty", column: "house" },
                { kind: "empty", column: "lastUpdated" },
                { kind: "empty", column: "ops" },
              ]}
            />
          ) : null}
        </AdminDataTable>
        <ConfirmDialog open={editor.pendingDeleteId !== null} title="Delete liability" body="Delete this liability record?" confirmLabel="Delete" tone="danger" onConfirm={editor.confirmDelete} onCancel={editor.cancelDelete} />
        <ConfirmDialog open={editor.confirmOpen} title="Discard unsaved edits?" body="This liability has unsaved changes." confirmLabel="Discard" cancelLabel="Keep editing" tone="danger" onConfirm={editor.acceptPending} onCancel={editor.cancelPending} />
      </AdminRecordTable>
    </div>
  );
}
