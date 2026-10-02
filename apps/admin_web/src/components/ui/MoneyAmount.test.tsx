import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MoneyAmount } from "./MoneyAmount";

describe("MoneyAmount", () => {
  it("renders symbol, space, then the grouped value", () => {
    render(<MoneyAmount amount={2100} currency="GBP" />);
    expect(screen.getByText("£ 2,100.00")).toBeTruthy();
    expect(screen.getByText("£ 2,100.00").className).toContain("admin-money");
    expect(screen.getByText("£ 2,100.00").className).not.toContain("admin-money-negative");
  });

  it("marks negatives in red", () => {
    render(<MoneyAmount amount={-411.4} currency="USD" />);
    const node = screen.getByText("US$ -411.40");
    expect(node.className).toContain("admin-money");
    expect(node.className).toContain("admin-money-negative");
  });
});
