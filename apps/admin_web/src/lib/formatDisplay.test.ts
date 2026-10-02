import { describe, expect, it } from "vitest";
import {
  currencySymbol,
  formatDateTimeHKT,
  formatMoneyAmount,
  formatMoneyAmountWithoutCurrency,
  formatNonZeroMoneyLines,
} from "./formatDisplay";

describe("formatMoneyAmount", () => {
  it("formats as symbol, space, then the grouped value", () => {
    expect(formatMoneyAmount(3300.23, "HKD")).toBe("HK$ 3,300.23");
    expect(formatMoneyAmount(2100, "GBP")).toBe("£ 2,100.00");
    expect(formatMoneyAmount(1234.5, "USD")).toBe("US$ 1,234.50");
    expect(formatMoneyAmount(99, "EUR")).toBe("€ 99.00");
    expect(formatMoneyAmount(80, "CNY")).toBe("CN¥ 80.00");
    expect(formatMoneyAmount(12.5, "SGD")).toBe("S$ 12.50");
    expect(formatMoneyAmount(40, "AED")).toBe("AED 40.00");
  });

  it("puts the minus on the value, not the symbol", () => {
    expect(formatMoneyAmount(-411.4, "USD")).toBe("US$ -411.40");
    expect(formatMoneyAmount(-0.5, "HKD")).toBe("HK$ -0.50");
  });

  it("keeps extra fraction digits when asked", () => {
    expect(formatMoneyAmount(0.0042, "USD", { fractionDigits: 4 })).toBe("US$ 0.0042");
  });

  it("uses an em dash for non-finite amounts", () => {
    expect(formatMoneyAmount(Number.NaN, "HKD")).toBe("—");
  });
});

describe("currencySymbol", () => {
  it("maps supported codes to a stable Latin symbol", () => {
    expect(currencySymbol("hkd")).toBe("HK$");
    expect(currencySymbol("USD")).toBe("US$");
  });
});

describe("formatNonZeroMoneyLines", () => {
  it("lists every non-zero currency and puts HKD first", () => {
    const lines = formatNonZeroMoneyLines({ USD: -411.4, HKD: 1200, EUR: 0 });
    expect(lines).toEqual(["HK$ 1,200.00", "US$ -411.40"]);
  });

  it("uses an em dash when every amount is zero", () => {
    expect(formatNonZeroMoneyLines({ HKD: 0, USD: 0 })).toEqual(["—"]);
  });
});

describe("formatMoneyAmountWithoutCurrency", () => {
  it("omits the currency symbol from the string", () => {
    expect(formatMoneyAmountWithoutCurrency(1234.5, "USD")).toBe("1,234.50");
    expect(formatMoneyAmountWithoutCurrency(-1234.5)).toBe("-1,234.50");
    expect(formatMoneyAmount(1234.5, "USD")).toBe("US$ 1,234.50");
  });
});

describe("formatDateTimeHKT", () => {
  it("includes HKT suffix", () => {
    const s = formatDateTimeHKT("2026-05-26T14:12:00.000Z");
    expect(s).toContain("HKT");
    expect(s).toContain("2026");
  });

  it("returns em dash for invalid iso", () => {
    expect(formatDateTimeHKT("not-a-date")).toBe("—");
  });
});
