import { type FormEvent, useCallback, useMemo, useState } from "react";
import {
  coerceSupportedCurrency,
  GLOBAL_DEFAULT_CURRENCY,
  type CurrencyCode,
} from "../lib/currencies";
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
  AdminTableTotalCurrency,
  AdminTableTotalLabel,
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

const ACCOUNT_SORT_OPTIONS: readonly { readonly key: AccountsSortKey; readonly label: string }[] = [
  { key: "desc", label: "Description" },
  { key: "atype", label: "Account type" },
  { key: "amt", label: "Current balance" },
  { key: "stmt", label: "Last statement" },
  { key: "ccy", label: "Currency" },
  { key: "day", label: "Billing cycle day" },
  { key: "lastUpdated", label: "Last update" },
];

function compareAccounts(
  a: FinanceAccountRecord,
  b: FinanceAccountRecord,
  sortKey: AccountsSortKey,
  sortDir: "asc" | "desc",
): number {
  const dir = sortDir === "asc" ? 1 : -1;
  let cmp = 0;
  switch (sortKey) {
    case "desc":
      cmp = a.description.localeCompare(b.description, undefined, { sensitivity: "base" });
      break;
    case "atype":
      cmp = a.accountType.localeCompare(b.accountType, undefined, { sensitivity: "base" });
      break;
    case "day": {
      const da = a.billingCycleDay;
      const db = b.billingCycleDay;
      cmp = da === db ? 0 : da < db ? -1 : 1;
      break;
    }
    case "amt": {
      const ma = a.recordedValue;
      const mb = b.recordedValue;
      cmp = ma === mb ? 0 : ma < mb ? -1 : 1;
      break;
    }
    case "stmt": {
      const sa = accountTypeIsCreditCard(a.accountType) ? (a.lastStatementAmount ?? 0) : 0;
      const sb = accountTypeIsCreditCard(b.accountType) ? (b.lastStatementAmount ?? 0) : 0;
      cmp = sa === sb ? 0 : sa < sb ? -1 : 1;
      break;
    }
    case "ccy":
      cmp = a.currency.localeCompare(b.currency, undefined, { sensitivity: "base" });
      break;
    case "lastUpdated": {
      const sa = a.lastUpdated ?? "";
      const sb = b.lastUpdated ?? "";
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
  return a.id.localeCompare(b.id);
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
  const expanded = useExpandedRecord("account");
  const editingId =
    expanded.expandedId && expanded.expandedId !== DRAFT_RECORD_ID
      ? expanded.expandedId
      : null;
  const formOpen = expanded.expandedId !== null;

  const [sortKey, setSortKey] = useState<AccountsSortKey | null>("atype");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const onSort = useCallback((key: AccountsSortKey) => {
    setSortKey((prevKey) => {
      if (prevKey !== key) {
        setSortDir("asc");
        return key;
      }
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      return prevKey;
    });
  }, []);

  const [formError, setFormError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [descriptionInput, setDescriptionInput] = useState("");
  const [accountTypeInput, setAccountTypeInput] = useState<FinanceAccountType>("Bank Account");
  const [billingDayStr, setBillingDayStr] = useState("1");
  const [valueStr, setValueStr] = useState("");
  const [lastStatementStr, setLastStatementStr] = useState("");
  const [formCurrency, setFormCurrency] = useState(GLOBAL_DEFAULT_CURRENCY);
  const [tableFilter, setTableFilter] = useState("");
  const [totalDisplayCurrency, setTotalDisplayCurrency] = useState<CurrencyCode>(
    GLOBAL_DEFAULT_CURRENCY,
  );

  const tableColumns = useMemo((): AdminDataTableColumn[] => {
    const manualSort = sortKey !== null;
    const thAria = (
      key: AccountsSortKey,
    ): "ascending" | "descending" | "none" | "other" | undefined => {
      if (!manualSort) return undefined;
      if (sortKey === key) return sortDir === "asc" ? "ascending" : "descending";
      return "none";
    };
    const dirFor = (key: AccountsSortKey): "asc" | "desc" | null =>
      sortKey === key ? sortDir : null;

    return [
      {
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
        thAriaSort: thAria("desc"),
      },
      {
        key: "atype",
        header: (
          <TableSortHeaderButton
            label="Account Type"
            isActive={sortKey === "atype"}
            direction={dirFor("atype")}
            onClick={() => onSort("atype")}
          />
        ),
        className: "small",
        priority: "secondary",
        thAriaSort: thAria("atype"),
      },
      {
        key: "amt",
        header: (
          <TableSortHeaderButton
            label="Current Balance"
            isActive={sortKey === "amt"}
            direction={dirFor("amt")}
            onClick={() => onSort("amt")}
          />
        ),
        className: "small text-end",
        headerClassName: "text-end",
        thAriaSort: thAria("amt"),
      },
      {
        key: "stmt",
        header: (
          <TableSortHeaderButton
            label="Last Statement Amount"
            isActive={sortKey === "stmt"}
            direction={dirFor("stmt")}
            onClick={() => onSort("stmt")}
          />
        ),
        className: "small text-end",
        headerClassName: "text-end",
        priority: "tertiary",
        thAriaSort: thAria("stmt"),
      },
      {
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
      },
      {
        key: "day",
        header: (
          <TableSortHeaderButton
            label="Billing Cycle Day"
            isActive={sortKey === "day"}
            direction={dirFor("day")}
            onClick={() => onSort("day")}
          />
        ),
        className: "small text-end",
        headerClassName: "text-end",
        priority: "tertiary",
        thAriaSort: thAria("day"),
      },
      {
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
      },
      {
        key: "ops",
        header: <span className="visually-hidden">Operations</span>,
        className: "text-end admin-nowrap",
        headerClassName: "text-end",
      },
    ];
  }, [onSort, sortDir, sortKey]);

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

  function resetFields() {
    setFormError(null);
    setDescriptionInput("");
    setAccountTypeInput("Bank Account");
    setBillingDayStr("1");
    setValueStr("");
    setLastStatementStr("");
    setFormCurrency(GLOBAL_DEFAULT_CURRENCY);
  }

  function applyAccount(row: FinanceAccountRecord) {
    setFormError(null);
    setDescriptionInput(row.description);
    setAccountTypeInput(row.accountType);
    setBillingDayStr(String(row.billingCycleDay));
    setValueStr(String(row.recordedValue));
    setLastStatementStr(
      accountTypeIsCreditCard(row.accountType)
        ? String(row.lastStatementAmount ?? "")
        : "",
    );
    setFormCurrency(coerceSupportedCurrency(row.currency, GLOBAL_DEFAULT_CURRENCY));
  }

  function accountDirty(): boolean {
    if (!formOpen) return false;
    if (!editingId) {
      return (
        descriptionInput !== "" ||
        valueStr !== "" ||
        lastStatementStr !== "" ||
        accountTypeInput !== "Bank Account" ||
        billingDayStr !== "1" ||
        formCurrency !== GLOBAL_DEFAULT_CURRENCY
      );
    }
    const row = records.find((record) => record.id === editingId);
    if (!row) return false;
    const savedStatement = accountTypeIsCreditCard(row.accountType)
      ? String(row.lastStatementAmount ?? "")
      : "";
    return (
      descriptionInput !== row.description ||
      accountTypeInput !== row.accountType ||
      billingDayStr !== String(row.billingCycleDay) ||
      valueStr !== String(row.recordedValue) ||
      lastStatementStr !== savedStatement ||
      formCurrency !== coerceSupportedCurrency(row.currency, GLOBAL_DEFAULT_CURRENCY)
    );
  }

  const editingAccount = editingId
    ? (records.find((record) => record.id === editingId) ?? null)
    : null;
  useHydrateExpandedRecord({
    expandedId: expanded.expandedId,
    recordsReady: true,
    record: editingAccount,
    apply: applyAccount,
    onMissing: () => expanded.request(null, false),
  });

  function openEdit(row: FinanceAccountRecord) {
    expanded.toggle(row.id, accountDirty(), () => applyAccount(row), resetFields);
  }

  function openCreate() {
    if (expanded.expandedId === DRAFT_RECORD_ID) {
      expanded.request(null, accountDirty(), resetFields);
      return;
    }
    expanded.request(DRAFT_RECORD_ID, accountDirty(), resetFields);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const valueNum = parseAmount(valueStr);
    let billingCycleDay: number;
    if (accountTypeUsesBillingCycleDay(accountTypeInput)) {
      const dayParsed = Number.parseInt(billingDayStr.trim(), 10);
      if (!Number.isInteger(dayParsed) || dayParsed < 1 || dayParsed > 31) {
        setFormError("Billing cycle day must be a whole number from 1 to 31.");
        return;
      }
      billingCycleDay = dayParsed;
    } else if (editingId) {
      const prev = records.find((r) => r.id === editingId);
      billingCycleDay = prev?.billingCycleDay ?? 1;
    } else {
      billingCycleDay = 1;
    }
    if (valueNum === null) {
      setFormError("Current balance must be a valid number.");
      return;
    }
    let lastStatementNum: number | undefined;
    if (accountTypeIsCreditCard(accountTypeInput)) {
      const parsedStmt = parseAmount(lastStatementStr);
      if (parsedStmt === null) {
        setFormError("Last Statement Amount must be a valid number.");
        return;
      }
      lastStatementNum = parsedStmt;
    }
    const currency = coerceSupportedCurrency(formCurrency, GLOBAL_DEFAULT_CURRENCY);
    const id = editingId ?? newStatementLineId();
    const row: FinanceAccountRecord = {
      id,
      description: descriptionInput.trim(),
      accountType: accountTypeInput,
      billingCycleDay,
      recordedValue: valueNum,
      ...(lastStatementNum !== undefined ? { lastStatementAmount: lastStatementNum } : {}),
      currency,
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
    onPatch((prev) => prev.filter((r) => r.id !== id));
    if (editingId === id) {
      resetFields();
      expanded.request(null, false);
    }
    setPendingDeleteId(null);
  }

      const accountEditor = formOpen ? (
        <AdminEditorPanel
          formId={formId}
          onSubmit={submit}
          submitLabel={editingId ? "Update record" : "Add record"}
          isSaving={isSaving}
          error={formError}
        >
          <div className="row g-3">
            <div className="col-12 col-sm-6 col-lg-2">
              <label className="form-label small" htmlFor={`${sheetId}-description`}>
                Description
              </label>
              <input
                id={`${sheetId}-description`}
                type="text"
                className="form-control form-control-sm"
                value={descriptionInput}
                onChange={(ev) => setDescriptionInput(ev.target.value)}
                placeholder="e.g. bank or card name"
                autoComplete="off"
              />
            </div>
            <div className="col-12 col-sm-6 col-lg-2">
              <label className="form-label small" htmlFor={`${sheetId}-account-type`}>
                Account Type
              </label>
              <select
                id={`${sheetId}-account-type`}
                className="form-select form-select-sm"
                value={accountTypeInput}
                onChange={(ev) => {
                  const next = ev.target.value as FinanceAccountType;
                  setAccountTypeInput(next);
                  if (!accountTypeIsCreditCard(next)) {
                    setLastStatementStr("");
                  }
                }}
              >
                {FINANCE_ACCOUNT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div className="col-12 col-sm-6 col-lg-2">
              <label className="form-label small" htmlFor={`${sheetId}-value`}>
                Current Balance
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
            <div className="col-12 col-sm-6 col-lg-2">
              <label
                className="form-label small"
                htmlFor={accountTypeIsCreditCard(accountTypeInput) ? `${sheetId}-last-statement` : undefined}
              >
                Last Statement Amount
              </label>
              {accountTypeIsCreditCard(accountTypeInput) ? (
                <input
                  id={`${sheetId}-last-statement`}
                  type="number"
                  step="0.01"
                  className="form-control form-control-sm"
                  required
                  value={lastStatementStr}
                  onChange={(ev) => setLastStatementStr(ev.target.value)}
                />
              ) : (
                <div className="form-control form-control-sm bg-light text-muted" aria-hidden>
                  —
                </div>
              )}
            </div>
            <div className="col-12 col-sm-6 col-lg-2">
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
            <div className="col-12 col-sm-6 col-lg-2">
              <label
                className="form-label small"
                htmlFor={
                  accountTypeUsesBillingCycleDay(accountTypeInput)
                    ? `${sheetId}-billing-day`
                    : undefined
                }
              >
                Billing cycle day
              </label>
              {accountTypeUsesBillingCycleDay(accountTypeInput) ? (
                <input
                  id={`${sheetId}-billing-day`}
                  type="number"
                  min={1}
                  max={31}
                  step={1}
                  className="form-control form-control-sm"
                  required
                  value={billingDayStr}
                  onChange={(ev) => setBillingDayStr(ev.target.value)}
                />
              ) : (
                <div
                  className="form-control form-control-sm bg-light text-muted"
                  id={`${sheetId}-billing-day`}
                  aria-hidden
                >
                  —
                </div>
              )}
            </div>
          </div>
        </AdminEditorPanel>
      ) : null;

  return (
    <div>
      <AdminRecordTable
        label="Accounts"
        filters={
          <AdminFilterBar
            create={<AdminCreateButton label="New account" onClick={openCreate} />}
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
          sort={{
            options: ACCOUNT_SORT_OPTIONS,
            sortKey,
            direction: sortDir,
            onChange: (key, dir) => {
              setSortKey(key as AccountsSortKey | null);
              setSortDir(dir);
            },
          }}
        >
          {expanded.expandedId === DRAFT_RECORD_ID ? (
            <AdminExpandableRow colSpan={colSpan} expanded onToggle={openCreate} editor={accountEditor}>
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
                expanded={expanded.expandedId === r.id}
                onToggle={() => openEdit(r)}
                editor={accountEditor}
              >
                <AdminCell column="desc" className="small">
                  {r.description || "—"}
                  <AdminDataTableCellMeta>
                    {r.accountType} · {r.currency}
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
              </AdminExpandableRow>
            ))
          ) : (
            <AdminDataTableEmptyRow
              colSpan={colSpan}
              message={records.length ? "No records match the filter." : "No account records yet."}
            />
          )}
          {records.length > 0 ? (
            <tr className="table-group-divider table-secondary fw-semibold">
              <AdminCell column="desc" className="small">
                <AdminTableTotalLabel
                  needsFx={needsFx}
                  fxError={fxError}
                  fxLoading={fxLoading}
                  ratesQuery={ratesQuery}
                />
              </AdminCell>
              <AdminCell column="atype" className="small" />
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
                  id={`${sheetId}-total-ccy`}
                  value={totalDisplayCurrency}
                  onChange={setTotalDisplayCurrency}
                  disabled={fxLoading}
                />
              </AdminCell>
              <AdminCell column="stmt" className="small" />
              <AdminCell column="ccy" className="small" />
              <AdminCell column="day" className="small" />
              <AdminCell column="lastUpdated" className="small" />
              <AdminCell column="ops" className="small text-end" />
            </tr>
          ) : null}
        </AdminDataTable>
        <ConfirmDialog
          open={pendingDeleteId !== null}
          title="Delete account"
          body="Delete this account record?"
          confirmLabel="Delete"
          tone="danger"
          onConfirm={() => { if (pendingDeleteId) deleteRow(pendingDeleteId); }}
          onCancel={() => setPendingDeleteId(null)}
        />
        <ConfirmDialog
          open={expanded.confirmOpen}
          title="Discard unsaved edits?"
          body="This account has unsaved changes."
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
