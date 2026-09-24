import { type FormEvent, useCallback, useMemo, useState } from "react";
import {
  coerceSupportedCurrency,
  GLOBAL_DEFAULT_CURRENCY,
  type CurrencyCode,
} from "../lib/currencies";
import { convertAmountToBase, convertAmountWithBase } from "../lib/frankfurterRates";
import { parseAmount } from "../lib/formParse";
import {
  ASSET_TYPES,
  INVESTMENT_CATEGORIES,
  INVESTMENT_CRYPTO_CURRENCY_MAX_LEN,
  INVESTMENT_TICKER_MAX_LEN,
  investmentDetailsDisplay,
  investmentMarketSourceCurrency,
  investmentRecordCurrentValueInRowCurrency,
  investmentRecordFiatNotionalInQuoteCurrency,
  isInvestmentMarketPriced,
  newStatementLineId,
  type FinanceInvestmentRecord,
  type HouseKey,
  type AssetType,
  type InvestmentCategory,
} from "../lib/financeModel";
import { DRAFT_RECORD_ID } from "../lib/expandedRecord";
import { useExpandedRecord } from "../hooks/useExpandedRecord";
import { useHydrateExpandedRecord } from "../hooks/useHydrateExpandedRecord";
import { buildQuoteMap, type FinanceQuoteResult } from "../lib/financeQuotes";
import { useFinanceQuotes } from "../hooks/useFinanceQuotes";
import { useFrankfurterRatesForTotals } from "../hooks/useFrankfurterRatesForTotals";
import { formatDateUtc } from "../lib/formatDisplay";
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
  CurrencySelect,
  FrankfurterRatesFooterNote,
  MoneyAmount,
  StaleValuationBadge,
  TableSortHeaderButton,
} from "./ui";

function parseOptionalUnit(raw: string): number | undefined | null {
  const t = raw.trim();
  if (!t) {
    return undefined;
  }
  const n = Number.parseFloat(t);
  return Number.isFinite(n) ? n : null;
}

function investmentLastUpdatedDisplay(lastUpdated: string | undefined): string {
  if (!lastUpdated) {
    return "—";
  }
  return formatDateUtc(`${lastUpdated}T00:00:00.000Z`);
}

function formatUnitCell(unit: number | undefined): string {
  if (unit === undefined) {
    return "—";
  }
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 8 }).format(unit);
}

/**
 * For **sorting** by Current Value: notional in {@link displayCurrency} (Frankfurter when the
 * row currency differs). Table cells show notional in the row’s own currency instead.
 *
 * `valueInRowCcy` is the row's current value already in the row's own currency
 * (computed via the live ticker quote × Frankfurter for market-priced rows,
 * or the fiat notional fallback for everything else). When that value is
 * `undefined` (quote/FX still loading or errored), we fall back to the
 * fiat notional so the row still sorts predictably.
 */
function investmentNotionalInDisplayCurrency(
  r: FinanceInvestmentRecord,
  displayCurrency: CurrencyCode,
  rateByQuote: ReadonlyMap<string, number>,
  needsFxGlobal: boolean,
  ratesFetchSucceeded: boolean,
  valueInRowCcy: number | undefined,
): number {
  const notional =
    valueInRowCcy !== undefined ? valueInRowCcy : investmentRecordFiatNotionalInQuoteCurrency(r);
  const rowNeedsFx =
    r.currency.trim().toUpperCase() !== displayCurrency.trim().toUpperCase();
  if (!rowNeedsFx) return notional;
  if (needsFxGlobal && !ratesFetchSucceeded) return notional;
  try {
    return convertAmountToBase(notional, r.currency, displayCurrency, rateByQuote);
  } catch {
    return notional;
  }
}

type InvSortKey =
  | "cat"
  | "details"
  | "atype"
  | "prov"
  | "amt"
  | "ccy"
  | "unit"
  | "currVal"
  | "lastUpd";

const INVESTMENT_SORT_OPTIONS: readonly { readonly key: InvSortKey; readonly label: string }[] = [
  { key: "cat", label: "Category" },
  { key: "details", label: "Details" },
  { key: "atype", label: "Asset type" },
  { key: "prov", label: "Provider" },
  { key: "amt", label: "Principal" },
  { key: "ccy", label: "Currency" },
  { key: "unit", label: "Units" },
  { key: "currVal", label: "Current value" },
  { key: "lastUpd", label: "Last update" },
];

function compareInv(
  a: FinanceInvestmentRecord,
  b: FinanceInvestmentRecord,
  sortKey: InvSortKey,
  sortDir: "asc" | "desc",
  houseLabelByValue: ReadonlyMap<HouseKey, string>,
  rowNotionalInDisplayCurrencyForSort: (r: FinanceInvestmentRecord) => number,
): number {
  const dir = sortDir === "asc" ? 1 : -1;
  let cmp = 0;
  switch (sortKey) {
    case "cat":
      cmp = a.category.localeCompare(b.category, undefined, { sensitivity: "base" });
      break;
    case "details":
      cmp = investmentDetailsDisplay(a, houseLabelByValue).localeCompare(
        investmentDetailsDisplay(b, houseLabelByValue),
        undefined,
        { sensitivity: "base" },
      );
      break;
    case "atype":
      cmp = a.assetType.localeCompare(b.assetType, undefined, { sensitivity: "base" });
      break;
    case "prov":
      cmp = a.provider.localeCompare(b.provider, undefined, { sensitivity: "base" });
      break;
    case "amt": {
      const ma = a.principalAmount;
      const mb = b.principalAmount;
      cmp = ma === mb ? 0 : ma < mb ? -1 : 1;
      break;
    }
    case "ccy":
      cmp = a.currency.localeCompare(b.currency, undefined, { sensitivity: "base" });
      break;
    case "unit": {
      const ua = a.unit;
      const ub = b.unit;
      if (ua === undefined && ub === undefined) {
        cmp = 0;
      } else if (ua === undefined) {
        cmp = 1;
      } else if (ub === undefined) {
        cmp = -1;
      } else {
        cmp = ua === ub ? 0 : ua < ub ? -1 : 1;
      }
      break;
    }
    case "currVal": {
      const va = rowNotionalInDisplayCurrencyForSort(a);
      const vb = rowNotionalInDisplayCurrencyForSort(b);
      cmp = va === vb ? 0 : va < vb ? -1 : 1;
      break;
    }
    case "lastUpd": {
      const sa = a.lastUpdated ?? "";
      const sb = b.lastUpdated ?? "";
      cmp = sa.localeCompare(sb, undefined, { sensitivity: "base" });
      break;
    }
    default:
      break;
  }
  if (cmp !== 0) return dir * cmp;
  return a.id.localeCompare(b.id);
}

type FormState = {
  category: InvestmentCategory;
  assetType: AssetType;
  provider: string;
  principal: string;
  currency: string;
  unit: string;
  currentValue: string;
  relatedHouse: HouseKey | "";
  ticker: string;
  cryptoCurrency: string;
};

function formFromInvestment(row: FinanceInvestmentRecord): FormState {
  return {
    category: row.category,
    assetType: row.assetType,
    provider: row.provider,
    principal: String(row.principalAmount),
    currency: row.currency,
    unit: row.category === "Real Estate" ? "" : row.unit !== undefined ? String(row.unit) : "",
    currentValue:
      row.category === "Real Estate" ? String(row.currentValue ?? row.principalAmount) : "",
    relatedHouse:
      row.category === "Real Estate" &&
      (row.relatedHouse === "hillmarton" || row.relatedHouse === "morrison")
        ? row.relatedHouse
        : "",
    ticker: row.category === "ETF" ? (row.ticker ?? "") : "",
    cryptoCurrency: row.category === "Crypto" ? (row.cryptoCurrency ?? "") : "",
  };
}

export type FinanceInvestmentsPanelProps = {
  readonly records: readonly FinanceInvestmentRecord[];
  readonly onPatch: (
    patch: (prev: readonly FinanceInvestmentRecord[]) => FinanceInvestmentRecord[],
  ) => void;
  readonly isSaving?: boolean;
  readonly relatedHouseOptions: ReadonlyArray<{
    readonly value: HouseKey;
    readonly label: string;
  }>;
};

export function FinanceInvestmentsPanel({
  records,
  onPatch,
  relatedHouseOptions,
  isSaving = false,
}: FinanceInvestmentsPanelProps) {
  const sheetId = "investments";
  const defaultCategory = INVESTMENT_CATEGORIES[0];
  const hasHouseOptions = relatedHouseOptions.length > 0;
  const relatedHouseLabelByValue = useMemo(() => {
    const m = new Map<HouseKey, string>();
    for (const o of relatedHouseOptions) {
      m.set(o.value, o.label);
    }
    return m;
  }, [relatedHouseOptions]);

  const emptyForm = (): FormState => ({
    category: defaultCategory,
    assetType: "Fixed",
    provider: "",
    principal: "",
    currency: GLOBAL_DEFAULT_CURRENCY,
    unit: "",
    currentValue: "",
    relatedHouse: "",
    ticker: "",
    cryptoCurrency: "",
  });

  const [sortKey, setSortKey] = useState<InvSortKey | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const onSort = useCallback((key: InvSortKey) => {
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
      key: InvSortKey,
    ): "ascending" | "descending" | "none" | "other" | undefined => {
      if (!manualSort) return undefined;
      if (sortKey === key) return sortDir === "asc" ? "ascending" : "descending";
      return "none";
    };
    const dirFor = (key: InvSortKey): "asc" | "desc" | null =>
      sortKey === key ? sortDir : null;

    const cols: AdminDataTableColumn[] = [
      {
        key: "cat",
        header: (
          <TableSortHeaderButton
            label="Category"
            isActive={sortKey === "cat"}
            direction={dirFor("cat")}
            onClick={() => onSort("cat")}
          />
        ),
        className: "small",
        thAriaSort: thAria("cat"),
      },
    ];
    cols.push({
      key: "details",
      header: (
        <TableSortHeaderButton
          label="Details"
          isActive={sortKey === "details"}
          direction={dirFor("details")}
          onClick={() => onSort("details")}
        />
      ),
      className: "small",
      priority: "secondary",
      thAriaSort: thAria("details"),
    });
    cols.push(
      {
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
      },
      {
        key: "prov",
        header: (
          <TableSortHeaderButton
            label="Provider"
            isActive={sortKey === "prov"}
            direction={dirFor("prov")}
            onClick={() => onSort("prov")}
          />
        ),
        className: "small",
        priority: "secondary",
        thAriaSort: thAria("prov"),
      },
      {
        key: "amt",
        header: (
          <TableSortHeaderButton
            label="Principal"
            isActive={sortKey === "amt"}
            direction={dirFor("amt")}
            onClick={() => onSort("amt")}
            align="end"
          />
        ),
        className: "small text-end",
        headerClassName: "small text-end",
        // Current Value is the metric that matters on a phone; principal moves to md+.
        priority: "secondary",
        thAriaSort: thAria("amt"),
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
        key: "unit",
        header: (
          <TableSortHeaderButton
            label="Units"
            isActive={sortKey === "unit"}
            direction={dirFor("unit")}
            onClick={() => onSort("unit")}
            align="end"
          />
        ),
        className: "small text-end",
        headerClassName: "small text-end",
        priority: "tertiary",
        thAriaSort: thAria("unit"),
      },
      {
        key: "currVal",
        header: (
          <TableSortHeaderButton
            label="Current Value"
            isActive={sortKey === "currVal"}
            direction={dirFor("currVal")}
            onClick={() => onSort("currVal")}
            align="end"
          />
        ),
        className: "small text-end",
        headerClassName: "small text-end",
        thAriaSort: thAria("currVal"),
      },
      {
        key: "lastUpd",
        header: (
          <TableSortHeaderButton
            label="Last Update"
            isActive={sortKey === "lastUpd"}
            direction={dirFor("lastUpd")}
            onClick={() => onSort("lastUpd")}
          />
        ),
        className: "small admin-nowrap",
        priority: "tertiary",
        thAriaSort: thAria("lastUpd"),
      },
      {
        key: "ops",
        header: <span className="visually-hidden">Operations</span>,
        className: "text-end admin-nowrap",
        headerClassName: "text-end",
      },
    );
    return cols;
  }, [sortKey, sortDir, onSort]);

  const colSpan = tableColumns.length;
  const formId = `${sheetId}-form`;
  const expanded = useExpandedRecord("investment");
  const editingId =
    expanded.expandedId && expanded.expandedId !== DRAFT_RECORD_ID
      ? expanded.expandedId
      : null;
  const formOpen = expanded.expandedId !== null;
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(() => emptyForm());
  const [tableFilter, setTableFilter] = useState("");
  const [totalDisplayCurrency, setTotalDisplayCurrency] = useState<CurrencyCode>(
    GLOBAL_DEFAULT_CURRENCY,
  );

  // Live spot prices for Crypto/ETF rows. The user-entered crypto code or
  // ETF ticker (e.g. ``BTC``, ``US:TQQQ``) is fetched from the admin
  // ``/finance/quotes`` endpoint, which proxies Yahoo Finance. The result
  // is then FX-converted into the row currency via Frankfurter.
  const marketPricedSymbols = useMemo(() => {
    const symbols: string[] = [];
    for (const r of records) {
      if (!isInvestmentMarketPriced(r)) continue;
      const src = investmentMarketSourceCurrency(r);
      if (src) symbols.push(src);
    }
    return symbols;
  }, [records]);
  const quotesQuery = useFinanceQuotes(marketPricedSymbols);
  const quoteByOriginalSymbol = useMemo<ReadonlyMap<string, FinanceQuoteResult>>(
    () => buildQuoteMap(quotesQuery.data ?? []),
    [quotesQuery.data],
  );
  const quotesPending = marketPricedSymbols.length > 0 && quotesQuery.isPending;
  const quotesErrored = marketPricedSymbols.length > 0 && quotesQuery.isError;

  // Frankfurter rates for: row currencies + every distinct currency reported
  // by the resolved quotes. The latter only kicks in once quotes resolve, so
  // this query naturally chains behind ``quotesQuery``.
  const fxQuoteCurrencies = useMemo(() => {
    const quotes: string[] = [];
    for (const r of records) {
      quotes.push(r.currency);
    }
    for (const q of quotesQuery.data ?? []) {
      if (q.currency) quotes.push(q.currency);
    }
    return quotes;
  }, [records, quotesQuery.data]);
  const { needsFx, ratesQuery, rateByQuoteForDisplay, fxLoading, fxError } =
    useFrankfurterRatesForTotals(totalDisplayCurrency, fxQuoteCurrencies);

  /**
   * For a market-priced row's source code → row.currency:
   * 1) Resolve the live quote (price in the venue's reporting currency).
   * 2) Convert that price into the row currency via Frankfurter.
   * Returns ``undefined`` when the quote or FX rate is unavailable.
   */
  const oneUnitConverter = useCallback(
    (sourceCode: string, rowCurrency: string): number | undefined => {
      const q = quoteByOriginalSymbol.get(sourceCode);
      if (!q || q.price === undefined || q.currency === undefined) {
        return undefined;
      }
      const quoteCcy = q.currency.trim().toUpperCase();
      const rowCcy = rowCurrency.trim().toUpperCase();
      if (quoteCcy === rowCcy) return q.price;
      // FX is needed, but rates may still be loading or have errored.
      if (needsFx && !ratesQuery.isSuccess) return undefined;
      try {
        return convertAmountWithBase(
          q.price,
          quoteCcy,
          rowCcy,
          totalDisplayCurrency,
          rateByQuoteForDisplay,
        );
      } catch {
        return undefined;
      }
    },
    [
      quoteByOriginalSymbol,
      needsFx,
      ratesQuery.isSuccess,
      totalDisplayCurrency,
      rateByQuoteForDisplay,
    ],
  );

  const currentValueInRowCurrencyByRowId = useMemo<
    ReadonlyMap<string, number | undefined>
  >(() => {
    const m = new Map<string, number | undefined>();
    for (const r of records) {
      m.set(
        r.id,
        investmentRecordCurrentValueInRowCurrency(r, oneUnitConverter),
      );
    }
    return m;
  }, [records, oneUnitConverter]);

  const rowNotionalInDisplayCurrencyForSort = useCallback(
    (r: FinanceInvestmentRecord): number =>
      investmentNotionalInDisplayCurrency(
        r,
        totalDisplayCurrency,
        rateByQuoteForDisplay,
        needsFx,
        ratesQuery.isSuccess,
        currentValueInRowCurrencyByRowId.get(r.id),
      ),
    [
      totalDisplayCurrency,
      rateByQuoteForDisplay,
      needsFx,
      ratesQuery.isSuccess,
      currentValueInRowCurrencyByRowId,
    ],
  );

  const filtered = useMemo(() => {
    const q = tableFilter.trim().toLowerCase();
    const list = !q
      ? [...records]
      : records.filter((r) => {
          const detailsHay = investmentDetailsDisplay(r, relatedHouseLabelByValue);
          const hay = [
            r.category,
            r.assetType,
            r.provider,
            r.currency,
            String(r.principalAmount),
            r.unit !== undefined ? String(r.unit) : "",
            r.lastUpdated ?? "",
            detailsHay,
            r.relatedHouse ?? "",
            r.ticker ?? "",
            r.cryptoCurrency ?? "",
            r.currentValue !== undefined ? String(r.currentValue) : "",
          ]
            .join(" ")
            .toLowerCase();
          return hay.includes(q);
        });
    if (sortKey !== null) {
      list.sort((a, b) =>
        compareInv(a, b, sortKey, sortDir, relatedHouseLabelByValue, rowNotionalInDisplayCurrencyForSort),
      );
    } else {
      list.sort((a, b) => {
        const byCcy = a.currency.localeCompare(b.currency, undefined, { sensitivity: "base" });
        if (byCcy !== 0) return byCcy;
        const byCat = a.category.localeCompare(b.category, undefined, { sensitivity: "base" });
        if (byCat !== 0) return byCat;
        const byDetails = investmentDetailsDisplay(a, relatedHouseLabelByValue).localeCompare(
          investmentDetailsDisplay(b, relatedHouseLabelByValue),
          undefined,
          { sensitivity: "base" },
        );
        if (byDetails !== 0) return byDetails;
        return a.provider.localeCompare(b.provider, undefined, { sensitivity: "base" });
      });
    }
    return list;
  }, [
    records,
    tableFilter,
    sortKey,
    sortDir,
    relatedHouseLabelByValue,
    rowNotionalInDisplayCurrencyForSort,
  ]);

  const convertedPrincipalTotal = useMemo(() => {
    if (filtered.length === 0) {
      return records.length === 0 ? null : 0;
    }
    if (needsFx) {
      if (!ratesQuery.isSuccess) return null;
      if (!ratesQuery.data) return null;
    }
    try {
      return filtered.reduce(
        (sum, r) =>
          sum +
          convertAmountToBase(
            r.principalAmount,
            r.currency,
            totalDisplayCurrency,
            rateByQuoteForDisplay,
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
    rateByQuoteForDisplay,
    totalDisplayCurrency,
  ]);

  const convertedCurrentValueTotal = useMemo(() => {
    if (filtered.length === 0) {
      return records.length === 0 ? null : 0;
    }
    if (needsFx) {
      if (!ratesQuery.isSuccess) return null;
      if (!ratesQuery.data) return null;
    }
    if (quotesPending || quotesErrored) return null;
    try {
      return filtered.reduce((sum, r) => {
        const valueInRowCcy = currentValueInRowCurrencyByRowId.get(r.id);
        const value =
          valueInRowCcy !== undefined
            ? valueInRowCcy
            : investmentRecordFiatNotionalInQuoteCurrency(r);
        return (
          sum +
          convertAmountToBase(value, r.currency, totalDisplayCurrency, rateByQuoteForDisplay)
        );
      }, 0);
    } catch {
      return null;
    }
  }, [
    filtered,
    records.length,
    needsFx,
    ratesQuery.isSuccess,
    ratesQuery.data,
    rateByQuoteForDisplay,
    totalDisplayCurrency,
    currentValueInRowCurrencyByRowId,
    quotesPending,
    quotesErrored,
  ]);

  function resetFields() {
    setFormError(null);
    setForm(emptyForm());
  }

  function applyInvestment(row: FinanceInvestmentRecord) {
    setFormError(null);
    setForm(formFromInvestment(row));
  }

  function investmentDirty(): boolean {
    if (!formOpen) return false;
    if (!editingId) return JSON.stringify(form) !== JSON.stringify(emptyForm());
    const row = records.find((record) => record.id === editingId);
    if (!row) return false;
    return JSON.stringify(form) !== JSON.stringify(formFromInvestment(row));
  }

  const editingInvestment = editingId
    ? (records.find((record) => record.id === editingId) ?? null)
    : null;
  useHydrateExpandedRecord({
    expandedId: expanded.expandedId,
    recordsReady: true,
    record: editingInvestment,
    apply: applyInvestment,
    onMissing: () => expanded.request(null, false),
  });

  function openEdit(row: FinanceInvestmentRecord) {
    expanded.toggle(row.id, investmentDirty(), () => applyInvestment(row), resetFields);
  }

  function openCreate() {
    if (expanded.expandedId === DRAFT_RECORD_ID) {
      expanded.request(null, investmentDirty(), resetFields);
      return;
    }
    expanded.request(DRAFT_RECORD_ID, investmentDirty(), resetFields);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const principalAmount = parseAmount(form.principal);
    if (!form.provider.trim()) {
      setFormError("Provider is required.");
      return;
    }
    if (principalAmount === null) {
      setFormError("Principal must be a valid number.");
      return;
    }
    const unitParsed =
      form.category === "Real Estate" ? undefined : parseOptionalUnit(form.unit);
    if (form.category !== "Real Estate" && unitParsed === null) {
      setFormError("Units must be a valid number.");
      return;
    }
    let realEstateCurrentValue: number | undefined;
    if (form.category === "Real Estate") {
      const cv = parseAmount(form.currentValue);
      if (cv === null) {
        setFormError("Current value must be a valid number.");
        return;
      }
      realEstateCurrentValue = cv;
    }
    if (!INVESTMENT_CATEGORIES.includes(form.category)) {
      setFormError("Pick a valid category.");
      return;
    }
    if (!ASSET_TYPES.includes(form.assetType)) {
      setFormError("Pick a valid asset type.");
      return;
    }
    const currency = coerceSupportedCurrency(form.currency, GLOBAL_DEFAULT_CURRENCY);
    const tickerTrim = form.ticker.trim();
    const cryptoTrim = form.cryptoCurrency.trim();
    const row: FinanceInvestmentRecord = {
      id: editingId ?? newStatementLineId(),
      category: form.category,
      assetType: form.assetType,
      provider: form.provider.trim(),
      principalAmount,
      currency,
      ...(form.category !== "Real Estate" &&
      unitParsed !== undefined &&
      unitParsed !== null
        ? { unit: unitParsed }
        : {}),
      ...(form.category === "Real Estate" && realEstateCurrentValue !== undefined
        ? { currentValue: realEstateCurrentValue }
        : {}),
      ...(form.category === "Real Estate" &&
      (form.relatedHouse === "hillmarton" || form.relatedHouse === "morrison")
        ? { relatedHouse: form.relatedHouse }
        : {}),
      ...(form.category === "ETF" && tickerTrim ? { ticker: tickerTrim } : {}),
      ...(form.category === "Crypto" && cryptoTrim ? { cryptoCurrency: cryptoTrim } : {}),
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

  const investmentEditor = formOpen ? (
    <AdminEditorPanel
      formId={formId}
      onSubmit={submit}
      submitLabel={editingId ? "Update record" : "Add record"}
      isSaving={isSaving}
      error={formError}
    >
          <div className="row g-3">
            <div className="col-12 col-md-2">
              <label className="form-label small" htmlFor={`${sheetId}-cat`}>
                Category
              </label>
              <select
                id={`${sheetId}-cat`}
                className="form-select form-select-sm"
                value={form.category}
                onChange={(ev) => {
                  const category = ev.target.value as InvestmentCategory;
                  setForm((f) => ({
                    ...f,
                    category,
                    relatedHouse: "",
                    ticker: "",
                    cryptoCurrency: "",
                    unit: category === "Real Estate" ? "" : f.unit,
                    currentValue:
                      category === "Real Estate"
                        ? f.principal.trim() !== ""
                          ? f.principal
                          : ""
                        : "",
                  }));
                }}
              >
                {INVESTMENT_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            {(form.category === "Real Estate" && hasHouseOptions) ||
            form.category === "ETF" ||
            form.category === "Crypto" ? (
              <div className="col-12 col-md-2">
                <label className="form-label small" htmlFor={`${sheetId}-details`}>
                  Details
                </label>
                {form.category === "Real Estate" ? (
                  <select
                    id={`${sheetId}-details`}
                    className="form-select form-select-sm"
                    value={form.relatedHouse}
                    onChange={(ev) =>
                      setForm((f) => ({
                        ...f,
                        relatedHouse: ev.target.value as HouseKey | "",
                      }))
                    }
                  >
                    <option value="">— None —</option>
                    {relatedHouseOptions.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                ) : form.category === "ETF" ? (
                  <input
                    id={`${sheetId}-details`}
                    type="text"
                    className="form-control form-control-sm"
                    maxLength={INVESTMENT_TICKER_MAX_LEN}
                    value={form.ticker}
                    onChange={(ev) => setForm((f) => ({ ...f, ticker: ev.target.value }))}
                  />
                ) : (
                  <input
                    id={`${sheetId}-details`}
                    type="text"
                    className="form-control form-control-sm"
                    maxLength={INVESTMENT_CRYPTO_CURRENCY_MAX_LEN}
                    value={form.cryptoCurrency}
                    onChange={(ev) =>
                      setForm((f) => ({ ...f, cryptoCurrency: ev.target.value }))
                    }
                  />
                )}
              </div>
            ) : null}
            <div className="col-12 col-md-2">
              <label className="form-label small" htmlFor={`${sheetId}-atype`}>
                Asset type
              </label>
              <select
                id={`${sheetId}-atype`}
                className="form-select form-select-sm"
                value={form.assetType}
                onChange={(ev) =>
                  setForm((f) => ({ ...f, assetType: ev.target.value as AssetType }))
                }
              >
                {ASSET_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div className="col-12 col-md-2">
              <label className="form-label small" htmlFor={`${sheetId}-prov`}>
                Provider
              </label>
              <input
                id={`${sheetId}-prov`}
                type="text"
                className="form-control form-control-sm"
                required
                value={form.provider}
                onChange={(ev) => setForm((f) => ({ ...f, provider: ev.target.value }))}
              />
            </div>
            <div className="col-12 col-md-2">
              <label className="form-label small" htmlFor={`${sheetId}-principal`}>
                Principal
              </label>
              <input
                id={`${sheetId}-principal`}
                type="number"
                step="0.01"
                className="form-control form-control-sm"
                required
                value={form.principal}
                onChange={(ev) => setForm((f) => ({ ...f, principal: ev.target.value }))}
              />
            </div>
            <div className="col-12 col-md-2">
              <label className="form-label small" htmlFor={`${sheetId}-ccy`}>
                Currency
              </label>
              <CurrencySelect
                id={`${sheetId}-ccy`}
                value={form.currency}
                onChange={(code) => setForm((f) => ({ ...f, currency: code }))}
              />
            </div>
            {form.category === "Real Estate" ? (
              <div className="col-12 col-md-2">
                <label className="form-label small" htmlFor={`${sheetId}-curval`}>
                  Current value
                </label>
                <input
                  id={`${sheetId}-curval`}
                  type="number"
                  step="0.01"
                  className="form-control form-control-sm"
                  required
                  value={form.currentValue}
                  onChange={(ev) => setForm((f) => ({ ...f, currentValue: ev.target.value }))}
                />
              </div>
            ) : null}
            {form.category !== "Real Estate" ? (
              <div className="col-12 col-md-2">
                <label className="form-label small" htmlFor={`${sheetId}-unit`}>
                  Units
                </label>
                <input
                  id={`${sheetId}-unit`}
                  type="number"
                  step="any"
                  className="form-control form-control-sm"
                  value={form.unit}
                  onChange={(ev) => setForm((f) => ({ ...f, unit: ev.target.value }))}
                />
              </div>
            ) : null}
          </div>
    </AdminEditorPanel>
  ) : null;

  return (
    <div>
      <AdminRecordTable
        label="Investments"
        filters={
          <AdminFilterBar
            create={<AdminCreateButton label="New investment" onClick={openCreate} />}
          >
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
          sort={{
            options: INVESTMENT_SORT_OPTIONS,
            sortKey,
            direction: sortDir,
            onChange: (key, dir) => {
              setSortKey(key as InvSortKey | null);
              setSortDir(dir);
            },
          }}
        >
          {expanded.expandedId === DRAFT_RECORD_ID ? (
            <AdminExpandableRow colSpan={colSpan} expanded onToggle={openCreate} editor={investmentEditor}>
              <AdminCell column="cat">New investment</AdminCell>
              <AdminCell column="details" />
              <AdminCell column="atype" />
              <AdminCell column="prov" />
              <AdminCell column="amt" />
              <AdminCell column="ccy" />
              <AdminCell column="unit" />
              <AdminCell column="currVal" />
              <AdminCell column="lastUpd" />
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
                editor={investmentEditor}
              >
                <AdminCell column="cat" className="small">
                  {r.category}
                  <AdminDataTableCellMeta>
                    {r.provider}
                    {investmentDetailsDisplay(r, relatedHouseLabelByValue)
                      ? ` · ${investmentDetailsDisplay(r, relatedHouseLabelByValue)}`
                      : ""}
                    {" · "}
                    Principal{" "}
                    <MoneyAmount amount={r.principalAmount} currency={r.currency} />
                  </AdminDataTableCellMeta>
                  <AdminDataTableCellMeta until="tertiary">
                    <StaleValuationBadge lastUpdated={r.lastUpdated} />
                  </AdminDataTableCellMeta>
                </AdminCell>
                <AdminCell column="details" className="small text-muted">
                  {investmentDetailsDisplay(r, relatedHouseLabelByValue) || "—"}
                </AdminCell>
                <AdminCell column="atype" className="small">{r.assetType}</AdminCell>
                <AdminCell column="prov" className="small">{r.provider}</AdminCell>
                <AdminCell column="amt" className="small text-end">
                  <MoneyAmount amount={r.principalAmount} currency={r.currency} amountOnly />
                </AdminCell>
                <AdminCell column="ccy" className="small">{r.currency}</AdminCell>
                <AdminCell column="unit" className="small text-end">
                  {r.category === "Real Estate" ? "—" : formatUnitCell(r.unit)}
                </AdminCell>
                <AdminCell column="currVal" className="small text-end">
                  {(() => {
                    const marketPriced = isInvestmentMarketPriced(r);
                    if (marketPriced) {
                      const sym = investmentMarketSourceCurrency(r);
                      const q = sym ? quoteByOriginalSymbol.get(sym) : undefined;
                      if (quotesPending) {
                        return (
                          <span
                            className="text-muted"
                            title="Loading live spot price…"
                          >
                            —
                          </span>
                        );
                      }
                      if (quotesErrored) {
                        return (
                          <span
                            className="text-danger"
                            title="Could not load live spot prices."
                          >
                            —
                          </span>
                        );
                      }
                      if (q?.error) {
                        return (
                          <span className="text-danger" title={q.error}>
                            —
                          </span>
                        );
                      }
                      if (needsFx && ratesQuery.isPending) {
                        return <span className="text-muted">—</span>;
                      }
                      if (needsFx && ratesQuery.isError) {
                        return <span className="text-muted">—</span>;
                      }
                    }
                    const valueInRowCcy = currentValueInRowCurrencyByRowId.get(r.id);
                    if (valueInRowCcy === undefined) {
                      return <span className="text-muted">—</span>;
                    }
                    return (
                      <MoneyAmount amount={valueInRowCcy} currency={r.currency} amountOnly />
                    );
                  })()}
                </AdminCell>
                <AdminCell column="lastUpd" className="small text-muted">
                  {investmentLastUpdatedDisplay(r.lastUpdated)}
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
              message={
                records.length ? "No records match the filter." : "No investment records yet."
              }
            />
          )}
          {records.length > 0 ? (
            <tr className="table-group-divider table-secondary fw-semibold">
              <AdminCell column="cat" className="small">
                Total
                <span className="d-block small text-muted fw-normal admin-table-total-note">
                  {quotesPending ? (
                    "Loading quotes…"
                  ) : quotesErrored ? (
                    <span className="text-danger">
                      {quotesQuery.error?.message ?? "Could not load quotes."}
                    </span>
                  ) : (
                    <FrankfurterRatesFooterNote
                      needsFx={needsFx}
                      fxError={fxError}
                      fxLoading={fxLoading}
                      ratesQuery={ratesQuery}
                    />
                  )}
                </span>
              </AdminCell>
              <AdminCell column="details" className="small" />
              <AdminCell column="atype" className="small" />
              <AdminCell column="prov" className="small" />
              <AdminCell column="amt" className="small text-end">
                {(() => {
                  if (needsFx && ratesQuery.isPending) {
                    return <span className="text-muted">—</span>;
                  }
                  if (needsFx && ratesQuery.isError) {
                    return <span className="text-muted">—</span>;
                  }
                  if (convertedPrincipalTotal !== null) {
                    return (
                      <MoneyAmount
                        amount={convertedPrincipalTotal}
                        currency={totalDisplayCurrency}
                        amountOnly
                      />
                    );
                  }
                  return <span className="text-muted">—</span>;
                })()}
              </AdminCell>
              <AdminCell column="ccy" className="small" />
              <AdminCell column="unit" className="small" />
              <AdminCell column="currVal" className="small text-end">
                {(() => {
                  if (needsFx && ratesQuery.isPending) {
                    return <span className="text-muted">—</span>;
                  }
                  if (needsFx && ratesQuery.isError) {
                    return <span className="text-muted">—</span>;
                  }
                  if (convertedCurrentValueTotal !== null) {
                    return (
                      <MoneyAmount
                        amount={convertedCurrentValueTotal}
                        currency={totalDisplayCurrency}
                        amountOnly
                      />
                    );
                  }
                  return <span className="text-muted">—</span>;
                })()}
                <br />
                <AdminTableTotalCurrency
                  id={`${sheetId}-total-ccy`}
                  value={totalDisplayCurrency}
                  onChange={setTotalDisplayCurrency}
                  disabled={fxLoading}
                />
              </AdminCell>
              <AdminCell column="lastUpd" className="small" />
              <AdminCell column="ops" className="small text-end" />
            </tr>
          ) : null}
        </AdminDataTable>
        <ConfirmDialog
          open={pendingDeleteId !== null}
          title="Delete investment"
          body="Delete this investment record?"
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
          body="This investment has unsaved changes."
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
