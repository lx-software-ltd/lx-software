import {
  formatMoneyAmount,
  formatMoneyAmountWithoutCurrency,
} from "../../lib/formatDisplay";

export type MoneyAmountProps = {
  readonly amount: number;
  readonly currency: string;
  readonly className?: string;
  /** When true, only the numeric part is shown (currency is omitted). */
  readonly amountOnly?: boolean;
  /** ISO code then the numeric part (`GBP 2,100.00`). Overrides `amountOnly`. */
  readonly codePrefix?: boolean;
};

/** Renders a currency amount using ISO currency codes and `Intl.NumberFormat`. */
export function MoneyAmount({
  amount,
  currency,
  className,
  amountOnly = false,
  codePrefix = false,
}: MoneyAmountProps) {
  const bare = formatMoneyAmountWithoutCurrency(amount, currency);
  const text = codePrefix
    ? `${currency} ${bare}`
    : amountOnly
      ? bare
      : formatMoneyAmount(amount, currency);
  return <span className={className ?? undefined}>{text}</span>;
}
