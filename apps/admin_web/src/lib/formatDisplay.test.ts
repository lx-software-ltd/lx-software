import { describe, expect, it } from "vitest";
import {
  formatDateTimeHKT,
  formatMoneyAmount,
  formatMoneyAmountWithoutCurrency,
  formatNonZeroMoneyLines,
} from "./formatDisplay";

describe("formatMoneyAmount", () => {
  it("formats HKD", () => {
    expect(formatMoneyAmount(12.5, "HKD")).toMatch(/12/);
  });
});

describe("formatNonZeroMoneyLines", () => {
  it("lists every non-zero currency and puts HKD first", () => {
    const lines = formatNonZeroMoneyLines({ USD: -411.4, HKD: 1200, EUR: 0 });
    expect(lines).toHaveLength(2);
    expect(lines[0]).toMatch(/HK/);
    expect(lines[0]).toMatch(/1,?200/);
    expect(lines[1]).toMatch(/411/);
  });

  it("uses an em dash when every amount is zero", () => {
    expect(formatNonZeroMoneyLines({ HKD: 0, USD: 0 })).toEqual(["—"]);
  });
});

describe("formatMoneyAmountWithoutCurrency", () => {
  it("omits ISO currency code from the string", () => {
    const full = formatMoneyAmount(1234.5, "USD");
    const bare = formatMoneyAmountWithoutCurrency(1234.5, "USD");
    expect(bare).not.toMatch(/\bUSD\b/);
    expect(full).toMatch(/\bUSD\b|^\$/);
    expect(bare).toMatch(/1,?234/);
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
