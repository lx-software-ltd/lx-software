/**
 * Live spot prices for Investment tickers / crypto codes via the admin
 * `/v1/admin/finance/quotes` proxy (Yahoo Finance upstream).
 *
 * The user enters symbols in TradingView style (`US:TQQQ`, `LON:VWRA`,
 * `HK:0700`) for ETF rows and the bare coin code (`BTC`, `ETH`) for
 * Crypto rows. The backend normalizes those to Yahoo Finance symbols and
 * returns the spot price in the venue's reporting currency. Sub-unit
 * currencies (GBp, ZAc, ILA) are normalized server-side to the major unit.
 */

import { AdminApiError, adminFetch } from "./apiAdminClient";

export type FinanceQuoteResult = {
  /** Original (user-entered) symbol the caller asked for. */
  readonly symbol: string;
  /** Yahoo Finance symbol the backend resolved the input to. */
  readonly yahooSymbol: string;
  /** Spot price in {@link currency}, when available. */
  readonly price?: number;
  /** ISO 4217 (or recognised pseudo-) currency reported by Yahoo. */
  readonly currency?: string;
  /** Upstream / mapping error message when the quote could not be resolved. */
  readonly error?: string;
};

export async function fetchFinanceQuotes(
  symbols: readonly string[],
): Promise<readonly FinanceQuoteResult[]> {
  const cleaned = [
    ...new Set(symbols.map((s) => s.trim()).filter((s) => s.length > 0)),
  ];
  if (cleaned.length === 0) {
    return [];
  }
  const param = cleaned.map((s) => encodeURIComponent(s)).join(",");
  let res: Response;
  try {
    res = await adminFetch(`/v1/admin/finance/quotes?symbols=${param}`);
  } catch (err) {
    if (err instanceof AdminApiError) {
      throw new Error(
        `Quotes request failed (${err.status}) ${err.responseBody}`.slice(0, 240),
      );
    }
    throw err;
  }
  const rows = (await res.json()) as unknown;
  if (!Array.isArray(rows)) {
    throw new Error("Quotes: unexpected response shape");
  }
  const out: FinanceQuoteResult[] = [];
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const o = row as Record<string, unknown>;
    const symbol = typeof o.symbol === "string" ? o.symbol : "";
    if (!symbol) continue;
    const yahooSymbol = typeof o.yahooSymbol === "string" ? o.yahooSymbol : symbol;
    const price = typeof o.price === "number" && Number.isFinite(o.price) ? o.price : undefined;
    const currency =
      typeof o.currency === "string" && o.currency.trim() ? o.currency.trim() : undefined;
    const error = typeof o.error === "string" ? o.error : undefined;
    out.push({
      symbol,
      yahooSymbol,
      ...(price !== undefined ? { price } : {}),
      ...(currency ? { currency } : {}),
      ...(error ? { error } : {}),
    });
  }
  return out;
}

/** Convenience: build a `Map<originalSymbol, FinanceQuoteResult>` for O(1) lookup by panel rows. */
export function buildQuoteMap(
  quotes: readonly FinanceQuoteResult[],
): ReadonlyMap<string, FinanceQuoteResult> {
  const m = new Map<string, FinanceQuoteResult>();
  for (const q of quotes) {
    m.set(q.symbol, q);
  }
  return m;
}
