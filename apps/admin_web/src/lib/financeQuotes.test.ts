import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildQuoteMap, fetchFinanceQuotes } from "./financeQuotes";

vi.mock("./auth", () => ({
  ensureFreshTokens: async () => "test-id-token",
  getStoredIdToken: () => "test-id-token",
  clearStoredSession: () => undefined,
}));

const ORIGINAL_FETCH = global.fetch;

beforeEach(() => {
  vi.stubEnv("VITE_API_BASE_URL", "https://api.example/admin");
  vi.stubEnv("VITE_COGNITO_CLIENT_ID", "test-client-id");
  vi.stubEnv("VITE_COGNITO_DOMAIN", "https://example.auth.us-east-1.amazoncognito.com");
  vi.stubEnv("VITE_COGNITO_REDIRECT_URI", "https://app.example/auth/callback");
});

afterEach(() => {
  global.fetch = ORIGINAL_FETCH;
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("fetchFinanceQuotes", () => {
  it("dedupes / trims / encodes the symbols query and parses the response", async () => {
    let capturedUrl: string | undefined;
    global.fetch = vi.fn(async (url: RequestInfo | URL) => {
      capturedUrl = String(url);
      return new Response(
        JSON.stringify([
          {
            symbol: "US:TQQQ",
            yahooSymbol: "TQQQ",
            price: 78.45,
            currency: "USD",
          },
          {
            symbol: "BTC",
            yahooSymbol: "BTC-USD",
            price: 95000,
            currency: "USD",
          },
          {
            symbol: "INVALID",
            yahooSymbol: "INVALID",
            error: "Quote not found",
          },
        ]),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as unknown as typeof fetch;

    const out = await fetchFinanceQuotes([
      "US:TQQQ",
      " US:TQQQ ",
      "BTC",
      "INVALID",
      "",
    ]);

    expect(capturedUrl).toContain("/finance/quotes?symbols=");
    // Trims & dedupes US:TQQQ; encodes the colon.
    expect(capturedUrl).toContain("US%3ATQQQ");
    expect(capturedUrl).toContain("BTC");
    expect(capturedUrl).toContain("INVALID");

    expect(out).toHaveLength(3);
    expect(out[0]).toMatchObject({
      symbol: "US:TQQQ",
      yahooSymbol: "TQQQ",
      price: 78.45,
      currency: "USD",
    });
    expect(out[1]).toMatchObject({
      symbol: "BTC",
      yahooSymbol: "BTC-USD",
      price: 95000,
      currency: "USD",
    });
    expect(out[2]).toMatchObject({
      symbol: "INVALID",
      yahooSymbol: "INVALID",
      error: "Quote not found",
    });
    expect(out[2].price).toBeUndefined();
    expect(out[2].currency).toBeUndefined();
  });

  it("returns [] without making a request when input is empty/whitespace", async () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    const out = await fetchFinanceQuotes(["", "  "]);
    expect(out).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("drops malformed rows from the upstream response", async () => {
    global.fetch = vi.fn(
      async () =>
        new Response(
          JSON.stringify([
            null,
            { symbol: "" },
            { yahooSymbol: "FOO" },
            { symbol: "BAR", price: "not-a-number", currency: "USD" },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    ) as unknown as typeof fetch;

    const out = await fetchFinanceQuotes(["BAR"]);
    expect(out).toHaveLength(1);
    expect(out[0].symbol).toBe("BAR");
    expect(out[0].price).toBeUndefined();
    expect(out[0].currency).toBe("USD");
  });
});

describe("buildQuoteMap", () => {
  it("maps quotes by their original symbol", () => {
    const m = buildQuoteMap([
      { symbol: "US:TQQQ", yahooSymbol: "TQQQ", price: 1, currency: "USD" },
      { symbol: "BTC", yahooSymbol: "BTC-USD", price: 2, currency: "USD" },
    ]);
    expect(m.get("US:TQQQ")?.price).toBe(1);
    expect(m.get("BTC")?.price).toBe(2);
    expect(m.get("ETH")).toBeUndefined();
  });
});

describe("integration: quote × Frankfurter → row currency", () => {
  it("computes ETF current value in row currency via quote + FX", async () => {
    const { investmentRecordCurrentValueInRowCurrency } = await import(
      "./financeModel"
    );
    const { convertAmountWithBase } = await import("./frankfurterRates");

    // 100 shares of US:TQQQ. Yahoo says 1 share = 78.45 USD. Row currency
    // is HKD; Frankfurter says 1 HKD = 0.12754 USD ⇒ 1 USD = 7.84 HKD.
    const quotes = buildQuoteMap([
      {
        symbol: "US:TQQQ",
        yahooSymbol: "TQQQ",
        price: 78.45,
        currency: "USD",
      },
    ]);
    const rateByQuote = new Map([["USD", 0.12754]]);
    const v = investmentRecordCurrentValueInRowCurrency(
      {
        id: "1",
        category: "ETF",
        assetType: "Liquid",
        provider: "Broker",
        principalAmount: 0,
        currency: "HKD",
        unit: 100,
        ticker: "US:TQQQ",
      },
      (sourceCode, rowCurrency) => {
        const q = quotes.get(sourceCode);
        if (!q || q.price === undefined || q.currency === undefined) return undefined;
        const quoteCcy = q.currency.toUpperCase();
        const rowCcy = rowCurrency.toUpperCase();
        if (quoteCcy === rowCcy) return q.price;
        return convertAmountWithBase(q.price, quoteCcy, rowCcy, "HKD", rateByQuote);
      },
    );

    // 100 × (78.45 / 0.12754) HKD ≈ 61509.32
    expect(v).toBeCloseTo(100 * (78.45 / 0.12754), 2);
  });

  it("returns undefined when the quote is missing", async () => {
    const { investmentRecordCurrentValueInRowCurrency } = await import(
      "./financeModel"
    );
    const v = investmentRecordCurrentValueInRowCurrency(
      {
        id: "1",
        category: "Crypto",
        assetType: "Liquid",
        provider: "Ex",
        principalAmount: 0,
        currency: "USD",
        unit: 1,
        cryptoCurrency: "BTC",
      },
      () => undefined,
    );
    expect(v).toBeUndefined();
  });
});
