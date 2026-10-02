import { formatMoneyAmount, formatMoneyAmountWithoutCurrency } from "../../lib/formatDisplay";

export type MoneyAmountProps = {
  readonly amount: number;
  readonly currency: string;
  readonly className?: string;
  /** When true, only the numeric part is shown (currency is omitted). */
  readonly amountOnly?: boolean;
  readonly fractionDigits?: number;
};

function moneyClassName(amount: number, className?: string): string {
  return ["admin-money", amount < 0 ? "admin-money-negative" : "", className]
    .filter(Boolean)
    .join(" ");
}

/** Renders `HK$ 3,300.23`. Negative amounts are red; non-negative stay the default text colour. */
export function MoneyAmount({
  amount,
  currency,
  className,
  amountOnly = false,
  fractionDigits,
}: MoneyAmountProps) {
  const options = fractionDigits === undefined ? undefined : { fractionDigits };
  const text = amountOnly
    ? formatMoneyAmountWithoutCurrency(amount, currency, options)
    : formatMoneyAmount(amount, currency, options);
  return <span className={moneyClassName(amount, className)}>{text}</span>;
}
