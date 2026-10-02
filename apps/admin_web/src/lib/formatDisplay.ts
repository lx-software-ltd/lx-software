import { GLOBAL_DEFAULT_CURRENCY } from "./currencies";

/** Shared formatting for admin UI (money + Hong Kong local time display). */

const CURRENCY_SYMBOLS: Readonly<Record<string, string>> = {
  AED: "AED",
  CNY: "CN¥",
  EUR: "€",
  GBP: "£",
  HKD: "HK$",
  SGD: "S$",
  USD: "US$",
};

export type FormatMoneyAmountOptions = {
  readonly fractionDigits?: number;
};

export type MoneyAmountLine = {
  readonly amount: number;
  readonly currency: string;
};

export function normalizeCurrencyCode(currency: string): string {
  return currency.length === 3 ? currency.toUpperCase() : GLOBAL_DEFAULT_CURRENCY;
}

/** Latin / common symbol for a supported code (`HKD` → `HK$`). Unknown 3-letter codes stay as the code. */
export function currencySymbol(currency: string): string {
  const code = normalizeCurrencyCode(currency);
  return CURRENCY_SYMBOLS[code] ?? code;
}

/** Grouped number with a leading minus when negative (`3,300.23`, `-3,300.23`). */
export function formatMoneyNumber(amount: number, fractionDigits = 2): string {
  if (!Number.isFinite(amount)) return "—";
  const formatted = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(Math.abs(amount));
  return amount < 0 ? `-${formatted}` : formatted;
}

/** `HK$ 3,300.23` — symbol, space, then the signed grouped value. */
export function formatMoneyAmount(
  amount: number,
  currency: string,
  options: FormatMoneyAmountOptions = {},
): string {
  if (!Number.isFinite(amount)) return "—";
  return `${currencySymbol(currency)} ${formatMoneyNumber(amount, options.fractionDigits ?? 2)}`;
}

/**
 * Every non-zero currency in a bucket, with the house default (HKD) first.
 * An all-zero bucket is empty so callers can show an em dash.
 */
export function listNonZeroMoneyLines(
  buckets: Readonly<Record<string, number>>,
): readonly MoneyAmountLine[] {
  const preferred = GLOBAL_DEFAULT_CURRENCY;
  const entries = Object.entries(buckets).filter(
    ([, amount]) => Number.isFinite(amount) && amount !== 0,
  );
  entries.sort(([a], [b]) => {
    if (a === preferred) return -1;
    if (b === preferred) return 1;
    return a.localeCompare(b);
  });
  return entries.map(([currency, amount]) => ({ currency, amount }));
}

/**
 * Every non-zero currency in a bucket, with the house default (HKD) first.
 * An all-zero bucket is an em dash so a tile does not look like a single total.
 */
export function formatNonZeroMoneyLines(
  buckets: Readonly<Record<string, number>>,
): readonly string[] {
  const lines = listNonZeroMoneyLines(buckets);
  if (lines.length === 0) return ["—"];
  return lines.map(({ currency, amount }) => formatMoneyAmount(amount, currency));
}

/** Same digit grouping as {@link formatMoneyAmount}, but omits the currency symbol. */
export function formatMoneyAmountWithoutCurrency(
  amount: number,
  _currency?: string,
  options: FormatMoneyAmountOptions = {},
): string {
  return formatMoneyNumber(amount, options.fractionDigits ?? 2);
}

/**
 * Formats an ISO 8601 instant for display in Hong Kong time, e.g.
 * `May 26, 2026 at 10:12pm HKT`.
 */
export function formatDateTimeHKT(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return "—";
  }

  const dateFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Hong_Kong",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
  const dateParts = dateFmt.formatToParts(d);
  const month = dateParts.find((p) => p.type === "month")?.value ?? "";
  const day = dateParts.find((p) => p.type === "day")?.value ?? "";
  const year = dateParts.find((p) => p.type === "year")?.value ?? "";

  const timeFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Hong_Kong",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
  const timeParts = timeFmt.formatToParts(d);
  const hour = timeParts.find((p) => p.type === "hour")?.value ?? "";
  const minute = timeParts.find((p) => p.type === "minute")?.value ?? "";
  const dayPeriod =
    timeParts.find((p) => p.type === "dayPeriod")?.value?.toLowerCase() ?? "";

  return `${month} ${day}, ${year} at ${hour}:${minute}${dayPeriod} HKT`;
}

/** Calendar date in UTC (no time), e.g. `May 26, 2026`. */
export function formatDateUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(d);
}
