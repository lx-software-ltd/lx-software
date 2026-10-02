import { describe, expect, it } from "vitest";
import {
  convertAmountToBase,
  convertAmountWithBase,
  netGainsMinusExpensesInBase,
  quoteCurrenciesFromBuckets,
  sumAmountsToBase,
} from "./frankfurterRates";

describe("convertAmountToBase", () => {
  it("returns amount unchanged when currencies match", () => {
    expect(convertAmountToBase(42, "HKD", "HKD", new Map())).toBe(42);
  });

  it("divides by Frankfurter rate (1 base = rate quote)", () => {
    // 1 HKD = 0.12754 USD → 100 USD → 100 / 0.12754 HKD
    const rateByQuote = new Map([["USD", 0.12754]]);
    const hkd = convertAmountToBase(100, "USD", "HKD", rateByQuote);
    expect(hkd).toBeCloseTo(100 / 0.12754, 2);
  });
});

describe("convertAmountWithBase", () => {
  it("returns amount unchanged when from equals to", () => {
    expect(convertAmountWithBase(10, "USD", "USD", "HKD", new Map())).toBe(10);
  });

  it("multiplies by rate when from equals base", () => {
    // base = HKD, 1 HKD = 0.12754 USD → 50 HKD = 50 * 0.12754 USD
    const rateByQuote = new Map([["USD", 0.12754]]);
    expect(convertAmountWithBase(50, "HKD", "USD", "HKD", rateByQuote)).toBeCloseTo(
      50 * 0.12754,
      6,
    );
  });

  it("divides by rate when to equals base (same as convertAmountToBase)", () => {
    const rateByQuote = new Map([["USD", 0.12754]]);
    expect(convertAmountWithBase(100, "USD", "HKD", "HKD", rateByQuote)).toBeCloseTo(
      100 / 0.12754,
      2,
    );
  });

  it("chains via base when neither side is the base", () => {
    // base = HKD; 1 HKD = 0.12754 USD; 1 HKD = 0.11 EUR.
    // 100 USD → in HKD = 100 / 0.12754 → in EUR = (100 / 0.12754) * 0.11.
    const rateByQuote = new Map([
      ["USD", 0.12754],
      ["EUR", 0.11],
    ]);
    const eur = convertAmountWithBase(100, "USD", "EUR", "HKD", rateByQuote);
    expect(eur).toBeCloseTo((100 * 0.11) / 0.12754, 6);
  });

  it("throws when a needed rate is missing", () => {
    const rateByQuote = new Map([["USD", 0.12754]]);
    expect(() =>
      convertAmountWithBase(10, "BTC", "USD", "HKD", rateByQuote),
    ).toThrow();
  });
});

describe("quoteCurrenciesFromBuckets", () => {
  it("collects non-zero currencies across buckets", () => {
    expect(
      quoteCurrenciesFromBuckets({ HKD: 1200, USD: 0 }, { USD: 411.4, GBP: 0 }).sort(),
    ).toEqual(["HKD", "USD"]);
  });
});

describe("sumAmountsToBase", () => {
  it("leaves an all-HKD bucket unchanged", () => {
    expect(sumAmountsToBase({ HKD: 1200, USD: 0 }, "HKD", new Map())).toBe(1200);
  });

  it("converts each currency then sums", () => {
    const rateByQuote = new Map([["USD", 0.12754]]);
    expect(sumAmountsToBase({ HKD: 100, USD: 10 }, "HKD", rateByQuote)).toBeCloseTo(
      100 + 10 / 0.12754,
      6,
    );
  });
});

describe("netGainsMinusExpensesInBase", () => {
  it("converts gains and expenses to HKD before subtracting", () => {
    const rateByQuote = new Map([["USD", 0.12754]]);
    const net = netGainsMinusExpensesInBase(
      { HKD: 1200 },
      { USD: 411.4 },
      "HKD",
      rateByQuote,
    );
    expect(net).toBeCloseTo(1200 - 411.4 / 0.12754, 6);
  });

  it("returns a single HKD figure when every line is already HKD", () => {
    expect(
      netGainsMinusExpensesInBase({ HKD: 48000 }, { HKD: 3800 }, "HKD", new Map()),
    ).toBe(44200);
  });
});
