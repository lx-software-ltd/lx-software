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
  FINANCE_ACCOUNT_TYPES,
  financeAccountSignedValueForTotal,
  newStatementLineId,
  type FinanceAccountRecord,
  type FinanceAccountType,
} from "../lib/financeModel";
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

function accountLastUpdatedDisplay(lastUpdated: string | undefined): string {
  if (!lastUpdated) {
    return "—";
  }
  return formatDateUtc(`${lastUpdated}T00:00:00.000Z`);
}

function accountTypeUsesBillingCycleDay(t: FinanceAccountType): boolean {
  return t !== "Bank Account";
}

function accountTypeIsCreditCard(t: FinanceAccountType): boolean {
  return t === "Credit Card";
}

type AccountsSortKey = "desc" | "atype" | "day" | "amt" | "stmt" | "ccy" | "lastUpdated";

type AccountFormState = {
  description: string;
  accountType: FinanceAccountType;
  billingDay: string;
  value: string;
  lastStatement: string;
  currency: CurrencyCode;
};

function emptyAccountForm(): AccountFormState {
  return {
    description: "",
    accountType: "Bank Account",
    billingDay: "1",
    value: "",
    lastStatement: "",
    currency: GLOBAL_DEFAULT_CURRENCY,
  };
}

function lineToForm(row: FinanceAccountRecord): AccountFormState {
  return {
    description: row.description,
    accountType: row.accountType,
    billingDay: String(row.billingCycleDay),
    value: String(row.recordedValue),
    lastStatement: accountTypeIsCreditCard(row.accountType)
      ? String(row.lastStatementAmount ?? "")
      : "",
    currency: coerceSupportedCurrency(row.currency, GLOBAL_DEFAULT_CURRENCY),
  };
}

function formToRecord(
  form: AccountFormState,
  editingId: string | null,
  previous: FinanceAccountRecord | null,
): { ok: true; record: FinanceAccountRecord } | { ok: false; error: string } {
  const valueNum = parseAmount(form.value);
  let billingCycleDay: number;
  if (accountTypeUsesBillingCycleDay(form.accountType)) {
    const dayParsed = Number.parseInt(form.billingDay.trim(), 10);
    if (!Number.isInteger(dayParsed) || dayParsed < 1 || dayParsed > 31) {
      return { ok: false, error: "Billing cycle day must be a whole number from 1 to 31." };
    }
    billingCycleDay = dayParsed;
  } else if (editingId) {
    billingCycleDay = previous?.billingCycleDay ?? 1;
  } else {
    billingCycleDay = 1;
  }
  if (valueNum === null) {
    return { ok: false, error: "Current balance must be a valid number." };
  }
  let lastStatementNum: number | undefined;
  if (accountTypeIsCreditCard(form.accountType)) {
    const parsedStmt = parseAmount(form.lastStatement);
    if (parsedStmt === null) {
      return { ok: false, error: "Last Statement Amount must be a valid number." };
    }
    lastStatementNum = parsedStmt;
  }
  const currency = coerceSupportedCurrency(form.currency, GLOBAL_DEFAULT_CURRENCY);
  return {
    ok: true,
    record: {
      id: editingId ?? newStatementLineId(),
      description: form.description.trim(),
      accountType: form.accountType,
      billingCycleDay,
      recordedValue: valueNum,
      ...(lastStatementNum !== undefined ? { lastStatementAmount: lastStatementNum } : {}),
      currency,
    },
  };
}

function compareAccounts(
  a: FinanceAccountRecord,
  b: FinanceAccountRecord,
  sortKey: AccountsSortKey,
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
        case "atype":
          return left.accountType.localeCompare(right.accountType, undefined, { sensitivity: "base" });
        case "day":
          return left.billingCycleDay === right.billingCycleDay
            ? 0
            : left.billingCycleDay < right.billingCycleDay
              ? -1
              : 1;
        case "amt":
          return left.recordedValue === right.recordedValue
            ? 0
            : left.recordedValue < right.recordedValue
              ? -1
              : 1;
        case "stmt": {
          const sa = accountTypeIsCreditCard(left.accountType) ? (left.lastStatementAmount ?? 0) : 0;
          const sb = accountTypeIsCreditCard(right.accountType) ? (right.lastStatementAmount ?? 0) : 0;
          return sa === sb ? 0 : sa < sb ? -1 : 1;
        }
        case "ccy":
          return left.currency.localeCompare(right.currency, undefined, { sensitivity: "base" });
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

export function FinanceAccountsPanel(props: {
  readonly records: readonly FinanceAccountRecord[];
  readonly onPatch: (
    patch: (prev: readonly FinanceAccountRecord[]) => FinanceAccountRecord[],
  ) => void;
  readonly isSaving?: boolean;
}) {
  const { records, onPatch, isSaving = false } = props;
  const sheetId = "accounts";
  const formId = `${sheetId}-form`;
  const { sortKey, sortDir, onSort, ariaSort, directionFor } = useSortState<AccountsSortKey>("atype");

  const [tableFilter, setTableFilter] = useState("");
  const [totalDisplayCurrency, setTotalDisplayCurrency] = useState<CurrencyCode>(
    GLOBAL_DEFAULT_CURRENCY,
  );

  const editor = useRecordEditor<AccountFormState, FinanceAccountRecord>({
    param: "account",
    records,
    emptyForm: emptyAccountForm,
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
        key: "atype",
        header: (
          <TableSortHeaderButton
            label="Account Type"
            isActive={sortKey === "atype"}
            direction={directionFor("atype")}
            onClick={() => onSort("atype")}
          />
        ),
        className: "small",
        priority: "secondary",
        thAriaSort: ariaSort("atype"),
      },
      {
        key: "amt",
        header: (
          <TableSortHeaderButton
            label="Current Balance"
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
        key: "stmt",
        header: (
          <TableSortHeaderButton
            label="Last Statement Amount"
            isActive={sortKey === "stmt"}
            direction={directionFor("stmt")}
            onClick={() => onSort("stmt")}
          />
        ),
        className: "small text-end",
        headerClassName: "text-end",
        priority: "tertiary",
        thAriaSort: ariaSort("stmt"),
      },
      {
        key: "ccy",
        header: (
          <TableSortHeaderButton
            label="Currency"
            isActive={sortKey === "ccy"}
            direction={directionFor("ccy")}
            onClick={() => onSort("ccy")}
          />
        ),
        className: "small",
        priority: "secondary",
        thAriaSort: ariaSort("ccy"),
      },
      {
        key: "day",
        header: (
          <TableSortHeaderButton
            label="Billing Cycle Day"
            isActive={sortKey === "day"}
            direction={directionFor("day")}
            onClick={() => onSort("day")}
          />
        ),
        className: "small text-end",
        headerClassName: "text-end",
        priority: "tertiary",
        thAriaSort: ariaSort("day"),
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
            r.accountType,
            ...(accountTypeUsesBillingCycleDay(r.accountType)
              ? [String(r.billingCycleDay)]
              : []),
            r.currency,
            String(r.recordedValue),
            ...(accountTypeIsCreditCard(r.accountType)
              ? [String(r.lastStatementAmount ?? "")]
              : []),
            r.lastUpdated ?? "",
          ]
            .join(" ")
            .toLowerCase();
          return hay.includes(q);
        });
    if (sortKey !== null) {
      list.sort((a, b) => compareAccounts(a, b, sortKey, sortDir));
    } else {
      list.sort((a, b) => {
        const byType = a.accountType.localeCompare(b.accountType, undefined, { sensitivity: "base" });
        if (byType !== 0) return byType;
        const byDesc = a.description.localeCompare(b.description, undefined, { sensitivity: "base" });
        if (byDesc !== 0) return byDesc;
        return a.currency.localeCompare(b.currency, undefined, { sensitivity: "base" });
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
          sum +
          convertAmountToBase(
            financeAccountSignedValueForTotal(r.accountType, r.recordedValue),
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

  function submit(e: FormEvent) {
    e.preventDefault();
    const built = formToRecord(editor.form, editor.editingId, editor.editingRecord);
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
  const creditCard = accountTypeIsCreditCard(form.accountType);
  const billingDay = accountTypeUsesBillingCycleDay(form.accountType);

  const accountEditor = editor.formOpen ? (
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
            value={form.description}
            onChange={(ev) =>
              editor.setForm((prev) => ({ ...prev, description: ev.target.value }))
            }
            placeholder="e.g. bank or card name"
            autoComplete="off"
          />
        </AdminField>
        <AdminField label="Account Type" htmlFor={`${sheetId}-account-type`}>
          <select
            id={`${sheetId}-account-type`}
            className="form-select form-select-sm"
            value={form.accountType}
            onChange={(ev) => {
              const next = ev.target.value as FinanceAccountType;
              editor.setForm((prev) => ({
                ...prev,
                accountType: next,
                lastStatement: accountTypeIsCreditCard(next) ? prev.lastStatement : "",
              }));
            }}
          >
            {FINANCE_ACCOUNT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </AdminField>
        <AdminField label="Current Balance" htmlFor={`${sheetId}-value`}>
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
        <AdminField label="Last Statement Amount" htmlFor={`${sheetId}-last-statement`}>
          {creditCard ? (
            <input
              id={`${sheetId}-last-statement`}
              type="number"
              step="0.01"
              className="form-control form-control-sm"
              required
              value={form.lastStatement}
              onChange={(ev) =>
                editor.setForm((prev) => ({ ...prev, lastStatement: ev.target.value }))
              }
            />
          ) : (
            <input
              id={`${sheetId}-last-statement`}
              type="text"
              className="form-control form-control-sm"
              value="—"
              disabled
            />
          )}
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
        <AdminField label="Billing cycle day" htmlFor={`${sheetId}-billing-day`}>
          {billingDay ? (
            <input
              id={`${sheetId}-billing-day`}
              type="number"
              min={1}
              max={31}
              step={1}
              className="form-control form-control-sm"
              required
              value={form.billingDay}
              onChange={(ev) =>
                editor.setForm((prev) => ({ ...prev, billingDay: ev.target.value }))
              }
            />
          ) : (
            <input
              id={`${sheetId}-billing-day`}
              type="text"
              className="form-control form-control-sm"
              value="—"
              disabled
            />
          )}
        </AdminField>
      </AdminFieldGrid>
    </AdminEditorPanel>
  ) : null;

  return (
    <div>
      <AdminRecordTable
        label="Accounts"
        filters={
          <AdminFilterBar
            create={<AdminCreateButton label="New account" onClick={editor.openCreate} />}
          >
            <AdminFilterField label="Filter" htmlFor="accounts-filter">
              <input
                id="accounts-filter"
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
          {editor.expandedId === "new" ? (
            <AdminExpandableRow colSpan={colSpan} expanded onToggle={editor.openCreate} editor={accountEditor}>
              <AdminCell column="desc">New account</AdminCell>
              <AdminCell column="atype" />
              <AdminCell column="amt" />
              <AdminCell column="stmt" />
              <AdminCell column="ccy" />
              <AdminCell column="day" />
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
                editor={accountEditor}
              >
                <AdminCell column="desc" className="small">
                  {r.description || "—"}
                  <AdminDataTableCellMeta>
                    {r.accountType} · {r.currency} ·{" "}
                    <MoneyAmount amount={r.recordedValue} currency={r.currency} />
                  </AdminDataTableCellMeta>
                  <AdminDataTableCellMeta until="tertiary">
                    <StaleValuationBadge lastUpdated={r.lastUpdated} />
                  </AdminDataTableCellMeta>
                </AdminCell>
                <AdminCell column="atype" className="small">{r.accountType}</AdminCell>
                <AdminCell column="amt" className="small text-end">
                  <MoneyAmount amount={r.recordedValue} currency={r.currency} amountOnly />
                </AdminCell>
                <AdminCell column="stmt" className="small text-end">
                  {accountTypeIsCreditCard(r.accountType) ? (
                    <MoneyAmount
                      amount={r.lastStatementAmount ?? 0}
                      currency={r.currency}
                      amountOnly
                    />
                  ) : (
                    "—"
                  )}
                </AdminCell>
                <AdminCell column="ccy" className="small">{r.currency}</AdminCell>
                <AdminCell column="day" className="small text-end">
                  {accountTypeUsesBillingCycleDay(r.accountType) ? r.billingCycleDay : "—"}
                </AdminCell>
                <AdminCell column="lastUpdated" className="small">
                  {accountLastUpdatedDisplay(r.lastUpdated)}
                  <StaleValuationBadge lastUpdated={r.lastUpdated} />
                </AdminCell>
                <AdminCell column="ops" className="small text-end">
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
              </AdminExpandableRow>
            ))
          ) : (
            <AdminDataTableEmptyRow
              colSpan={colSpan}
              message={records.length ? "No records match the filter." : "No account records yet."}
            />
          )}
          {records.length > 0 ? (
            <AdminFxTotalRow
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
                { kind: "empty", column: "atype" },
                { kind: "amount", column: "amt", total: convertedTotal, picker: true },
                { kind: "empty", column: "stmt" },
                { kind: "empty", column: "ccy" },
                { kind: "empty", column: "day" },
                { kind: "empty", column: "lastUpdated" },
                { kind: "empty", column: "ops" },
              ]}
            />
          ) : null}
        </AdminDataTable>
        <ConfirmDialog
          open={editor.pendingDeleteId !== null}
          title="Delete account"
          body="Delete this account record?"
          confirmLabel="Delete"
          tone="danger"
          onConfirm={editor.confirmDelete}
          onCancel={editor.cancelDelete}
        />
        <ConfirmDialog
          open={editor.confirmOpen}
          title="Discard unsaved edits?"
          body="This account has unsaved changes."
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
