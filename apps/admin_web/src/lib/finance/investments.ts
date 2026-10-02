import { type AssetType, type HouseKey } from "../financeTypes";
import type { FinanceInvestmentRecord } from "./types";


export function isAssetType(v: unknown): v is AssetType {
  return v === "Fixed" || v === "Liquid";
}


export function trimInvestmentDetailString(raw: unknown, maxLen: number): string | undefined {
  if (typeof raw !== "string") {
    return undefined;
  }
  const t = raw.trim();
  if (!t) {
    return undefined;
  }
  return t.length > maxLen ? t.slice(0, maxLen) : t;
}


/**
 * Fiat notional in {@link FinanceInvestmentRecord.currency} before cross-currency conversion
 * (e.g. Frankfurter).
 *
 * For **Crypto** with a positive `unit`, `principalAmount` is the spot fiat value of **one** unit
 * (coin/token) in the record currency — e.g. 1 BNB = 1 HKD — and the row total is `unit × principalAmount`.
 * Frankfurter converts that total when displaying in another ISO currency.
 * For Crypto without units, `principalAmount` is the total position in quote currency.
 *
 * For **Fixed Term Deposit** with a positive `unit`, the notional is `unit × principalAmount`
 * (e.g. lots × principal per lot); otherwise `principalAmount`.
 *
 * For **Real Estate**, uses {@link FinanceInvestmentRecord.currentValue} when set; otherwise
 * `principalAmount`.
 *
 * **ETF** uses `principalAmount` as the total in quote currency.
 */
export function investmentRecordFiatNotionalInQuoteCurrency(
  record: FinanceInvestmentRecord,
): number {
  const p = record.principalAmount;
  if (record.category === "Real Estate") {
    const cv = record.currentValue;
    if (cv !== undefined && Number.isFinite(cv)) {
      return cv;
    }
    return p;
  }
  if (record.category === "Fixed Term Deposit") {
    const u = record.unit;
    if (u !== undefined && Number.isFinite(u) && u > 0 && Number.isFinite(p)) {
      return u * p;
    }
    return p;
  }
  if (record.category !== "Crypto") return p;
  const u = record.unit;
  if (u !== undefined && Number.isFinite(u) && u > 0 && Number.isFinite(p)) {
    return u * p;
  }
  return p;
}


/**
 * Returns the per-row "market price source" currency code for an Investment row,
 * i.e. the symbol whose Frankfurter rate (against the row currency) is applied
 * to `unit` to compute the current value:
 *  - Crypto rows return the trimmed `cryptoCurrency` (when set).
 *  - ETF rows return the trimmed `ticker` (when set).
 *  - Other categories (or rows missing the field) return `undefined`.
 */
export function investmentMarketSourceCurrency(
  record: FinanceInvestmentRecord,
): string | undefined {
  if (record.category === "Crypto") {
    const v = record.cryptoCurrency?.trim();
    return v ? v : undefined;
  }
  if (record.category === "ETF") {
    const v = record.ticker?.trim();
    return v ? v : undefined;
  }
  return undefined;
}


/**
 * Whether {@link record} is a Crypto/ETF row eligible for market-priced current value:
 * has a positive numeric `unit` AND a non-empty `cryptoCurrency`/`ticker` field.
 * Rows where the market source equals the row currency still qualify (rate is identity).
 */
export function isInvestmentMarketPriced(record: FinanceInvestmentRecord): boolean {
  const src = investmentMarketSourceCurrency(record);
  if (!src) return false;
  const u = record.unit;
  return u !== undefined && Number.isFinite(u) && u > 0;
}


/**
 * Computes the current value of an Investment row in its own `currency`.
 *
 * For Crypto/ETF rows that are {@link isInvestmentMarketPriced market priced},
 * the value is `unit × rate(1 marketSource → row.currency)`, where the
 * rate is provided by `convertOneUnitToRowCurrency`. The callback may
 * throw or return `undefined` when the rate is unavailable; in that case
 * this function returns `undefined` so callers can render a placeholder.
 *
 * For all other rows (or when the row is not yet market-priced), falls back
 * to {@link investmentRecordFiatNotionalInQuoteCurrency}.
 */
export function investmentRecordCurrentValueInRowCurrency(
  record: FinanceInvestmentRecord,
  convertOneUnitToRowCurrency: (
    marketSourceCurrency: string,
    rowCurrency: string,
  ) => number | undefined,
): number | undefined {
  if (!isInvestmentMarketPriced(record)) {
    return investmentRecordFiatNotionalInQuoteCurrency(record);
  }
  const src = investmentMarketSourceCurrency(record);
  if (!src) {
    return investmentRecordFiatNotionalInQuoteCurrency(record);
  }
  const u = record.unit;
  if (u === undefined || !Number.isFinite(u)) {
    return investmentRecordFiatNotionalInQuoteCurrency(record);
  }
  let oneUnit: number | undefined;
  try {
    oneUnit = convertOneUnitToRowCurrency(src, record.currency);
  } catch {
    return undefined;
  }
  if (oneUnit === undefined || !Number.isFinite(oneUnit)) {
    return undefined;
  }
  return u * oneUnit;
}


/** Value shown in the Investments “Details” column (property, ticker, or crypto label). */
export function investmentDetailsDisplay(
  record: FinanceInvestmentRecord,
  houseLabelByValue: ReadonlyMap<HouseKey, string>,
): string {
  switch (record.category) {
    case "Real Estate": {
      if (!record.relatedHouse) {
        return "";
      }
      return houseLabelByValue.get(record.relatedHouse) ?? record.relatedHouse;
    }
    case "ETF":
      return record.ticker?.trim() ?? "";
    case "Crypto":
      return record.cryptoCurrency?.trim() ?? "";
    default:
      return "";
  }
}
