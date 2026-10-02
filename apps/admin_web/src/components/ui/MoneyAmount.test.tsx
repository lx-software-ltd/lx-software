import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { formatMoneyAmountWithoutCurrency } from "../../lib/formatDisplay";
import { MoneyAmount } from "./MoneyAmount";

describe("MoneyAmount", () => {
  it("prefixes the ISO code when codePrefix is set", () => {
    render(<MoneyAmount amount={2100} currency="GBP" codePrefix />);
    expect(
      screen.getByText(`GBP ${formatMoneyAmountWithoutCurrency(2100, "GBP")}`),
    ).toBeTruthy();
  });
});
