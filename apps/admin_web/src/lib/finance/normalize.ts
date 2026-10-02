import { GLOBAL_DEFAULT_CURRENCY, coerceSupportedCurrency } from "../currencies";
import {
  FINANCE_ACCOUNT_TYPES,
  FINANCE_LIABILITY_TYPES,
  INVESTMENT_CATEGORIES,
  INVESTMENT_CRYPTO_CURRENCY_MAX_LEN,
  INVESTMENT_TICKER_MAX_LEN,
  MAX_ACCOUNT_DESCRIPTION_LEN,
  MAX_PENSION_DESCRIPTION_LEN,
  type AssetType,
  type HouseKey,
} from "../financeTypes";
import { isAssetType, trimInvestmentDetailString } from "./investments";
import type {
  FinanceAccountRecord,
  FinanceAllocationRecord,
  FinanceInvestmentRecord,
  FinanceLedgerAmountPeriod,
  FinanceLedgerRecord,
  FinanceLiabilityRecord,
  FinancePensionRecord,
  FinanceSavingsRecord,
  HouseFinanceData,
  HouseFloat,
  HouseStatementLine,
  NormalizeLedgerRecordsOptions,
} from "./types";
import { CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX, emptyHouse } from "./types";
import { num, oneOf, str } from "./field";


/** Resolved attachment keys for a line (normalized data uses `sourceAssetKeys` only). */
export function statementLineAssetKeys(line: HouseStatementLine): readonly string[] {
  const keys = line.sourceAssetKeys;
  return keys?.length ? keys : [];
}


function mergeRawSourceAssetKeys(row: Record<string, unknown>): string[] | undefined {
  const merged: string[] = [];
  const rawArr = row.sourceAssetKeys;
  if (Array.isArray(rawArr)) {
    for (const x of rawArr) {
      if (typeof x === "string" && x.trim()) merged.push(x.trim());
    }
  }
  const legacy = row.sourceAssetKey;
  if (typeof legacy === "string" && legacy.trim()) merged.push(legacy.trim());
  const seen = new Set<string>();
  const out: string[] = [];
  for (const k of merged) {
    if (!seen.has(k)) {
      seen.add(k);
      out.push(k);
    }
  }
  return out.length ? out : undefined;
}


function categorySet(categories: readonly string[]): Set<string> {
  return new Set(categories);
}


/** Coerces API payloads into investment rows; drops invalid entries. */
export function normalizeInvestmentRecords(input: unknown): FinanceInvestmentRecord[] {
  if (!Array.isArray(input)) {
    return [];
  }
  const out: FinanceInvestmentRecord[] = [];
  for (const raw of input) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as Record<string, unknown>;
    const id = str(row, "id").trim();
    const category = oneOf(row.category, INVESTMENT_CATEGORIES);
    if (!id || !category) {
      continue;
    }
    if (!isAssetType(row.assetType)) {
      continue;
    }
    const assetType = row.assetType;
    const provider =
      str(row, "provider").trim();
    if (!provider) {
      continue;
    }
    const amtRaw = row.principalAmount;
    const principalAmount = num(amtRaw);
    if (!Number.isFinite(principalAmount) || Math.abs(principalAmount) > 1e15) {
      continue;
    }
    const curRaw = str(row, "currency") || GLOBAL_DEFAULT_CURRENCY;
    const currency = coerceSupportedCurrency(curRaw, GLOBAL_DEFAULT_CURRENCY);
    const rh = row.relatedHouse;
    const relatedHouse: HouseKey | undefined =
      category === "Real Estate" && (rh === "hillmarton" || rh === "morrison") ? rh : undefined;
    const ticker =
      category === "ETF"
        ? trimInvestmentDetailString(row.ticker, INVESTMENT_TICKER_MAX_LEN)
        : undefined;
    const cryptoCurrency =
      category === "Crypto"
        ? trimInvestmentDetailString(row.cryptoCurrency, INVESTMENT_CRYPTO_CURRENCY_MAX_LEN)
        : undefined;
    let unit: number | undefined;
    if (category !== "Real Estate") {
      const unitRaw = row.unit;
      if (unitRaw === undefined || unitRaw === null || unitRaw === "") {
        unit = undefined;
      } else {
        const n = num(unitRaw);
        if (!Number.isFinite(n) || Math.abs(n) > 1e15) {
          continue;
        }
        unit = n;
      }
    }
    let currentValue: number | undefined;
    if (category === "Real Estate") {
      const cvRaw = row.currentValue;
      if (cvRaw !== undefined && cvRaw !== null && cvRaw !== "") {
        const cvn = num(cvRaw);
        if (!Number.isFinite(cvn) || Math.abs(cvn) > 1e15) {
          continue;
        }
        currentValue = cvn;
      }
    }
    const lastUpdated = parseOptionalFinanceCalendarDateUtc(row.lastUpdated);
    out.push({
      id,
      category,
      currency,
      assetType,
      provider,
      principalAmount,
      ...(unit !== undefined ? { unit } : {}),
      ...(relatedHouse ? { relatedHouse } : {}),
      ...(currentValue !== undefined ? { currentValue } : {}),
      ...(ticker ? { ticker } : {}),
      ...(cryptoCurrency ? { cryptoCurrency } : {}),
      ...(lastUpdated !== undefined ? { lastUpdated } : {}),
    });
  }
  return out;
}


/** Coerces API payloads into savings rows; drops invalid entries. */
export function normalizeSavingsRecords(input: unknown): FinanceSavingsRecord[] {
  if (!Array.isArray(input)) {
    return [];
  }
  const out: FinanceSavingsRecord[] = [];
  for (const raw of input) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as Record<string, unknown>;
    const id = str(row, "id").trim();
    const deposit = str(row, "deposit").trim();
    if (!id || !deposit) {
      continue;
    }
    const amtRaw = row.value;
    const value = num(amtRaw);
    if (!Number.isFinite(value) || Math.abs(value) > 1e15) {
      continue;
    }
    const curRaw = str(row, "currency") || GLOBAL_DEFAULT_CURRENCY;
    const currency = coerceSupportedCurrency(curRaw, GLOBAL_DEFAULT_CURRENCY);
    let description = str(row, "description").trim();
    if (description.length > MAX_PENSION_DESCRIPTION_LEN) {
      description = description.slice(0, MAX_PENSION_DESCRIPTION_LEN);
    }
    const assetType: AssetType = isAssetType(row.assetType)
      ? row.assetType
      : "Fixed";
    out.push({ id, deposit, assetType, description, value, currency });
  }
  return out;
}


/** Valid `YYYY-MM-DD` calendar date in UTC (used for pension and investment `lastUpdated`). */
export function parseOptionalFinanceCalendarDateUtc(raw: unknown): string | undefined {
  if (typeof raw !== "string") {
    return undefined;
  }
  const s = raw.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    return undefined;
  }
  const ms = Date.parse(`${s}T00:00:00.000Z`);
  if (Number.isNaN(ms)) {
    return undefined;
  }
  if (new Date(ms).toISOString().slice(0, 10) !== s) {
    return undefined;
  }
  return s;
}


/** Coerces API payloads into pension rows; drops invalid entries. */
export function normalizePensionRecords(input: unknown): FinancePensionRecord[] {
  if (!Array.isArray(input)) {
    return [];
  }
  const out: FinancePensionRecord[] = [];
  for (const raw of input) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as Record<string, unknown>;
    const id = str(row, "id").trim();
    const fund = str(row, "fund").trim();
    if (!id || !fund) {
      continue;
    }
    const amtRaw = row.value;
    const value = num(amtRaw);
    if (!Number.isFinite(value) || Math.abs(value) > 1e15) {
      continue;
    }
    const curRaw = str(row, "currency") || GLOBAL_DEFAULT_CURRENCY;
    const currency = coerceSupportedCurrency(curRaw, GLOBAL_DEFAULT_CURRENCY);
    let description = str(row, "description").trim();
    if (description.length > MAX_PENSION_DESCRIPTION_LEN) {
      description = description.slice(0, MAX_PENSION_DESCRIPTION_LEN);
    }
    const lastUpdated = parseOptionalFinanceCalendarDateUtc(row.lastUpdated);
    const rec: FinancePensionRecord = { id, fund, description, value, currency };
    out.push(lastUpdated === undefined ? rec : { ...rec, lastUpdated });
  }
  return out;
}


/** Coerces API payloads into account rows; drops invalid entries. */
export function normalizeAccountRecords(input: unknown): FinanceAccountRecord[] {
  if (!Array.isArray(input)) {
    return [];
  }
  const out: FinanceAccountRecord[] = [];
  for (const raw of input) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as Record<string, unknown>;
    const id = str(row, "id").trim();
    const accountType = oneOf(str(row, "accountType").trim(), FINANCE_ACCOUNT_TYPES);
    if (!id || !accountType) {
      continue;
    }
    const dayRaw = row.billingCycleDay;
    let billingCycleDay: number;
    if (typeof dayRaw === "number" && Number.isInteger(dayRaw) && !Number.isNaN(dayRaw)) {
      billingCycleDay = dayRaw;
    } else if (typeof dayRaw === "string" && /^\d+$/.test(dayRaw.trim())) {
      billingCycleDay = Number.parseInt(dayRaw.trim(), 10);
    } else {
      continue;
    }
    if (billingCycleDay < 1 || billingCycleDay > 31) {
      continue;
    }
    const amtRaw = row.recordedValue;
    const recordedValue = num(amtRaw);
    if (!Number.isFinite(recordedValue) || Math.abs(recordedValue) > 1e15) {
      continue;
    }
    let lastStatementAmount: number | undefined;
    if (accountType === "Credit Card") {
      const lsaRaw = row.lastStatementAmount;
      let lsa: number;
      if (lsaRaw === undefined || lsaRaw === null || lsaRaw === "") {
        lsa = 0;
      } else if (typeof lsaRaw === "number") {
        lsa = lsaRaw;
      } else if (typeof lsaRaw === "string") {
        lsa = num(lsaRaw);
      } else {
        continue;
      }
      if (!Number.isFinite(lsa) || Math.abs(lsa) > 1e15) {
        continue;
      }
      lastStatementAmount = lsa;
    }
    const curRaw = str(row, "currency") || GLOBAL_DEFAULT_CURRENCY;
    const currency = coerceSupportedCurrency(curRaw, GLOBAL_DEFAULT_CURRENCY);
    let description = str(row, "description").trim();
    if (description.length > MAX_ACCOUNT_DESCRIPTION_LEN) {
      description = description.slice(0, MAX_ACCOUNT_DESCRIPTION_LEN);
    }
    const lastUpdated = parseOptionalFinanceCalendarDateUtc(row.lastUpdated);
    const rec: FinanceAccountRecord = {
      id,
      description,
      accountType,
      billingCycleDay,
      recordedValue,
      ...(lastStatementAmount !== undefined ? { lastStatementAmount } : {}),
      currency,
    };
    out.push(lastUpdated === undefined ? rec : { ...rec, lastUpdated });
  }
  return out;
}


/** Coerces API payloads into liability rows; drops invalid entries. */
export function normalizeLiabilityRecords(input: unknown): FinanceLiabilityRecord[] {
  if (!Array.isArray(input)) {
    return [];
  }
  const out: FinanceLiabilityRecord[] = [];
  for (const raw of input) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as Record<string, unknown>;
    const id = str(row, "id").trim();
    const description = str(row, "description").trim();
    const liabilityType = oneOf(str(row, "liabilityType").trim(), FINANCE_LIABILITY_TYPES);
    if (!id || !description || !liabilityType) {
      continue;
    }
    const amtRaw = row.outstandingBalance;
    const outstandingBalance = num(amtRaw);
    if (
      !Number.isFinite(outstandingBalance) ||
      outstandingBalance < 0 ||
      outstandingBalance > 1e15
    ) {
      continue;
    }
    const curRaw = str(row, "currency") || GLOBAL_DEFAULT_CURRENCY;
    const currency = coerceSupportedCurrency(curRaw, GLOBAL_DEFAULT_CURRENCY);
    let interestRatePercent: number | undefined;
    const rateRaw = row.interestRatePercent;
    if (typeof rateRaw === "number" && Number.isFinite(rateRaw)) {
      if (rateRaw >= 0 && rateRaw <= 100) {
        interestRatePercent = rateRaw;
      }
    }
    const rhRaw = row.relatedHouse;
    const relatedHouse: HouseKey | undefined =
      rhRaw === "hillmarton" || rhRaw === "morrison" ? rhRaw : undefined;
    const lastUpdated = parseOptionalFinanceCalendarDateUtc(row.lastUpdated);
    out.push({
      id,
      description,
      liabilityType,
      outstandingBalance,
      currency,
      ...(interestRatePercent !== undefined ? { interestRatePercent } : {}),
      ...(relatedHouse ? { relatedHouse } : {}),
      ...(lastUpdated !== undefined ? { lastUpdated } : {}),
    });
  }
  return out;
}


function parseIncomeLedgerFlag(row: Record<string, unknown>, key: string): boolean {
  const v = row[key];
  return v === true;
}


/** Coerces API payloads into ledger rows; drops entries with unknown categories. */
export function normalizeLedgerRecords(
  input: unknown,
  allowedCategories: readonly string[],
  options?: NormalizeLedgerRecordsOptions,
): FinanceLedgerRecord[] {
  if (!Array.isArray(input)) {
    return [];
  }
  const allowed = categorySet(allowedCategories);
  const includeIncomeFlags = options?.includeIncomeFlags === true;
  const includeExpenseFlags = options?.includeExpenseFlags === true;
  const out: FinanceLedgerRecord[] = [];
  for (const raw of input) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as Record<string, unknown>;
    const id = str(row, "id").trim();
    const category = str(row, "category");
    const description = str(row, "description").trim();
    if (!id || !allowed.has(category) || !description) {
      continue;
    }
    const amtRaw = row.amount;
    const amount = num(amtRaw);
    if (!Number.isFinite(amount) || Math.abs(amount) > 1e15) {
      continue;
    }
    const curRaw = str(row, "currency") || GLOBAL_DEFAULT_CURRENCY;
    const currency = coerceSupportedCurrency(curRaw, GLOBAL_DEFAULT_CURRENCY);
    const periodRaw = row.amountPeriod;
    const amountPeriod: FinanceLedgerAmountPeriod =
      periodRaw === "year" ? "year" : "month";
    const rh = row.relatedHouse;
    const relatedHouse: HouseKey | undefined =
      rh === "hillmarton" || rh === "morrison" ? rh : undefined;
    const base: FinanceLedgerRecord = {
      id,
      category,
      description,
      amount,
      currency,
      amountPeriod,
      ...(relatedHouse ? { relatedHouse } : {}),
    };
    if (includeIncomeFlags) {
      out.push({
        ...base,
        isTax: parseIncomeLedgerFlag(row, "isTax"),
        isSaving: parseIncomeLedgerFlag(row, "isSaving"),
        isInvestment: parseIncomeLedgerFlag(row, "isInvestment"),
      });
    } else if (includeExpenseFlags) {
      out.push({
        ...base,
        isAllocate: parseIncomeLedgerFlag(row, "isAllocate"),
      });
    } else {
      out.push(base);
    }
  }
  return out;
}


/** Coerces GET/PUT allocation tab payloads from the admin API. */
export function normalizeAllocationRecords(input: unknown): FinanceAllocationRecord[] {
  if (!Array.isArray(input)) {
    return [];
  }
  const out: FinanceAllocationRecord[] = [];
  for (const raw of input) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as Record<string, unknown>;
    const expenseId = str(row, "expenseId").trim();
    const description = str(row, "description").trim();
    if (!expenseId || !description) {
      continue;
    }
    const isCustomAllocation =
      row.isCustomAllocation === true ||
      expenseId.startsWith(CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX);
    const isIncome = row.isIncome === true;
    const isPension = row.isPension === true;
    const rhRaw = row.relatedHouse;
    const relatedHouse: HouseKey | undefined =
      rhRaw === "hillmarton" || rhRaw === "morrison" ? rhRaw : undefined;
    const monthlyRaw = row.monthlyAmount;
    let monthlyAmount: number;
    if (isCustomAllocation) {
      monthlyAmount = 0;
    } else {
      monthlyAmount =
        num(monthlyRaw);
      if (!Number.isFinite(monthlyAmount) || Math.abs(monthlyAmount) > 1e15) {
        continue;
      }
    }
    const accRaw = row.accumulatedAmount;
    const accumulatedAmount = num(accRaw);
    if (!Number.isFinite(accumulatedAmount) || Math.abs(accumulatedAmount) > 1e15) {
      continue;
    }
    const curRaw = str(row, "currency") || GLOBAL_DEFAULT_CURRENCY;
    const currency = coerceSupportedCurrency(curRaw, GLOBAL_DEFAULT_CURRENCY);
    const lastUpdated = parseOptionalFinanceCalendarDateUtc(row.lastUpdated);

    let allocationIncomeMonthly: number | undefined;
    if (isCustomAllocation && isIncome) {
      const incRaw = row.allocationIncomeMonthly ?? row.monthlyAmount;
      const inc =
        num(incRaw);
      if (Number.isFinite(inc) && Math.abs(inc) <= 1e15) {
        allocationIncomeMonthly = inc;
      }
    }

    const rec: FinanceAllocationRecord = {
      expenseId,
      description,
      monthlyAmount,
      accumulatedAmount,
      currency,
      ...(isCustomAllocation ? { isCustomAllocation: true as const } : {}),
      ...(isIncome ? { isIncome: true as const } : {}),
      ...(isPension ? { isPension: true as const } : {}),
      ...(allocationIncomeMonthly !== undefined ? { allocationIncomeMonthly } : {}),
      ...(relatedHouse ? { relatedHouse } : {}),
    };
    out.push(lastUpdated === undefined ? rec : { ...rec, lastUpdated });
  }
  return out;
}


export function newStatementLineId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `line-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}


/** Coerces API / legacy payloads into a consistent `HouseFinanceData` shape. */
export function normalizeHouseFinanceData(input: unknown): HouseFinanceData {
  if (!input || typeof input !== "object") {
    return emptyHouse();
  }
  const o = input as Record<string, unknown>;

  const defaultCurrency = coerceSupportedCurrency(
    str(o, "defaultCurrency") || GLOBAL_DEFAULT_CURRENCY,
    GLOBAL_DEFAULT_CURRENCY,
  );

  const fl = o.float;
  let float: HouseFloat;
  if (fl && typeof fl === "object") {
    const fo = fl as Record<string, unknown>;
    const amtRaw = fo.amount;
    const parsedAmt = num(amtRaw);
    const amt = typeof amtRaw === "number" && Number.isFinite(amtRaw) ? amtRaw : typeof amtRaw === "string" ? parsedAmt : 0;
    const amount = Number.isFinite(amt) ? amt : 0;
    const curRaw = str(fo, "currency") || defaultCurrency;
    float = {
      amount,
      currency: coerceSupportedCurrency(curRaw, defaultCurrency),
    };
  } else {
    float = { amount: 0, currency: defaultCurrency };
  }

  const linesRaw = o.lines;
  const linesOut: HouseStatementLine[] = [];
  if (Array.isArray(linesRaw)) {
    for (const raw of linesRaw) {
      if (!raw || typeof raw !== "object") continue;
      const row = raw as Record<string, unknown>;
      const id = str(row, "id");
      const dateUtc = str(row, "dateUtc");
      const type = oneOf(row.type, ["income", "expenditure", "mortgage"] as const);
      const description = str(row, "description");
      if (!id.trim() || !dateUtc || !type || !description.trim()) {
        continue;
      }
      const net = num(row.netAmount);
      const vat = num(row.vat);
      const gross = num(row.grossAmount);
      if (![net, vat, gross].every((n) => typeof n === "number" && Number.isFinite(n))) {
        continue;
      }
      const curRaw = typeof row.currency === "string" ? row.currency : defaultCurrency;
      const sourceAssetKeys = mergeRawSourceAssetKeys(row);
      linesOut.push({
        id: id.trim(),
        dateUtc: dateUtc.trim(),
        type,
        description: description.trim(),
        netAmount: net,
        vat,
        grossAmount: gross,
        currency: coerceSupportedCurrency(curRaw, defaultCurrency),
        ...(sourceAssetKeys?.length ? { sourceAssetKeys } : {}),
      });
    }
  }

  return {
    defaultCurrency,
    float,
    lines: linesOut,
  };
}
