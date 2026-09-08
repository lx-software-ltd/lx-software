import type { ReactNode } from "react";
import type { UsageMonth } from "../../lib/usageMonth";

export function UsageBillCard({
  title,
  monthAriaLabel,
  month,
  months,
  onMonthChange,
  isLoading,
  loadingMessage,
  isError,
  errorMessage,
  emptyMessage,
  children,
}: {
  readonly title: string;
  readonly monthAriaLabel: string;
  readonly month: UsageMonth;
  readonly months: readonly UsageMonth[];
  readonly onMonthChange: (key: string) => void;
  readonly isLoading: boolean;
  readonly loadingMessage: string;
  readonly isError: boolean;
  readonly errorMessage: string;
  readonly emptyMessage: string;
  readonly children: ReactNode;
}) {
  return (
    <div className="card h-100 shadow-sm">
      <div className="card-body d-flex flex-column">
        <h2 className="h6 text-uppercase text-muted">{title}</h2>
        <div className="mb-3">
          <select
            className="form-select form-select-sm"
            value={month.key}
            onChange={(event) => onMonthChange(event.target.value)}
            aria-label={monthAriaLabel}
          >
            {months.map((row) => (
              <option key={row.key} value={row.key}>
                {row.label}
              </option>
            ))}
          </select>
        </div>
        {isLoading ? (
          <p className="mb-0 small text-muted">{loadingMessage}</p>
        ) : isError ? (
          <p className="mb-0 small text-danger">{errorMessage}</p>
        ) : children ? (
          children
        ) : (
          <p className="mb-0 small text-muted">{emptyMessage}</p>
        )}
      </div>
    </div>
  );
}
