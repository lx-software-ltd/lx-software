/** ECB-oriented FX via admin API proxy (Frankfurter upstream). See https://www.frankfurter.dev/docs/ */

import { AdminApiError, adminFetch } from "./apiAdminClient";

/**
 * Fetches cross-rates with a chosen base. Each returned row means: `1 base` = `rate` units of `quote`.
 * To express an amount held in `quote` in terms of `base`, divide by `rate`: `amountBase = amountQuote / rate`.
 */
export async function fetchFrankfurterRatesToBase(
  base: string,
  quotes: readonly string[],
): Promise<{ readonly date: string | undefined; readonly rateByQuote: ReadonlyMap<string, number> }> {
  const upperBase = base.trim().toUpperCase();
  const need = [...new Set(quotes.map((q) => q.trim().toUpperCase()))].filter((q) => q !== upperBase);
  if (need.length === 0) {
    return { date: undefined, rateByQuote: new Map() };
  }

  const quotesParam = need.map((q) => encodeURIComponent(q)).join(",");
  const path = `/fx/v2/rates?base=${encodeURIComponent(upperBase)}&quotes=${quotesParam}`;
  let res: Response;
  try {
    res = await adminFetch(path);
  } catch (err) {
    if (err instanceof AdminApiError) {
      throw new Error(
        `Frankfurter request failed (${err.status}) ${err.responseBody}`.slice(0, 240),
      );
    }
    throw err;
  }

  const rows = (await res.json()) as unknown;
  if (!Array.isArray(rows)) {
    throw new Error("Frankfurter: unexpected response shape");
  }

  const rateByQuote = new Map<string, number>();
  let date: string | undefined;
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const o = row as Record<string, unknown>;
    const quote = typeof o.quote === "string" ? o.quote.toUpperCase() : "";
    const rate = typeof o.rate === "number" ? o.rate : Number.NaN;
    if (!quote || !Number.isFinite(rate) || rate <= 0) continue;
    rateByQuote.set(quote, rate);
    if (typeof o.date === "string") date = o.date;
  }

  for (const q of need) {
    if (!rateByQuote.has(q)) {
      throw new Error(`Frankfurter: missing rate for ${q} (base ${upperBase})`);
    }
  }

  return { date, rateByQuote };
}

/** Distinct currencies with a non-zero amount across one or more buckets. */
export function quoteCurrenciesFromBuckets(
  ...buckets: readonly Readonly<Record<string, number>>[]
): string[] {
  const codes = new Set<string>();
  for (const bucket of buckets) {
    for (const [currency, amount] of Object.entries(bucket)) {
      if (amount !== 0) codes.add(currency);
    }
  }
  return [...codes];
}

/** Sums a currency bucket after converting each amount into `toCurrency`. */
export function sumAmountsToBase(
  amounts: Readonly<Record<string, number>>,
  toCurrency: string,
  rateByQuote: ReadonlyMap<string, number>,
): number {
  return Object.entries(amounts).reduce((sum, [currency, amount]) => {
    if (amount === 0) return sum;
    return sum + convertAmountToBase(amount, currency, toCurrency, rateByQuote);
  }, 0);
}

/**
 * Converts every gain and expense into `toCurrency`, then returns gains minus expenses.
 * Zero-amount currencies are skipped; a missing Frankfurter rate throws.
 */
export function netGainsMinusExpensesInBase(
  gains: Readonly<Record<string, number>>,
  expenses: Readonly<Record<string, number>>,
  toCurrency: string,
  rateByQuote: ReadonlyMap<string, number>,
): number {
  return (
    sumAmountsToBase(gains, toCurrency, rateByQuote) -
    sumAmountsToBase(expenses, toCurrency, rateByQuote)
  );
}

/** Converts `amount` from `fromCurrency` into `toCurrency` using `rateByQuote` from {@link fetchFrankfurterRatesToBase} with `base === toCurrency`. */
export function convertAmountToBase(
  amount: number,
  fromCurrency: string,
  toCurrency: string,
  rateByQuote: ReadonlyMap<string, number>,
): number {
  const from = fromCurrency.trim().toUpperCase();
  const to = toCurrency.trim().toUpperCase();
  if (from === to) return amount;
  const r = rateByQuote.get(from);
  if (r === undefined || r <= 0) {
    throw new Error(`No conversion rate for ${from} → ${to}`);
  }
  return amount / r;
}

/**
 * Converts `amount` from `fromCurrency` into `toCurrency` given a {@link rateByQuote}
 * map fetched against `baseCurrency` (i.e. each entry means `1 baseCurrency = rate quote`).
 * Handles all four cases:
 *  - from === to: identity.
 *  - from === base: amount * rate(to).
 *  - to === base: amount / rate(from) (same as {@link convertAmountToBase}).
 *  - neither equals base: amount * rate(to) / rate(from).
 */
export function convertAmountWithBase(
  amount: number,
  fromCurrency: string,
  toCurrency: string,
  baseCurrency: string,
  rateByQuote: ReadonlyMap<string, number>,
): number {
  const from = fromCurrency.trim().toUpperCase();
  const to = toCurrency.trim().toUpperCase();
  const base = baseCurrency.trim().toUpperCase();
  if (from === to) return amount;
  if (from === base) {
    const rTo = rateByQuote.get(to);
    if (rTo === undefined || rTo <= 0) {
      throw new Error(`No conversion rate for ${from} → ${to}`);
    }
    return amount * rTo;
  }
  if (to === base) {
    const rFrom = rateByQuote.get(from);
    if (rFrom === undefined || rFrom <= 0) {
      throw new Error(`No conversion rate for ${from} → ${to}`);
    }
    return amount / rFrom;
  }
  const rFrom = rateByQuote.get(from);
  const rTo = rateByQuote.get(to);
  if (rFrom === undefined || rFrom <= 0 || rTo === undefined || rTo <= 0) {
    throw new Error(`No conversion rate for ${from} → ${to}`);
  }
  return (amount * rTo) / rFrom;
}
