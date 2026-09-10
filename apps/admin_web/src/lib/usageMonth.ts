/** UTC calendar months for the AWS / OpenRouter dashboard cards. */

export const USAGE_MONTH_LOOKBACK = 12;

export type UsageMonth = {
  readonly key: string;
  readonly from: string;
  readonly to: string;
  readonly label: string;
  readonly isCurrent: boolean;
};

function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

export function utcCalendarDay(now = new Date()): Date {
  return new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
  );
}

function isoDay(day: Date): string {
  return `${day.getUTCFullYear()}-${pad2(day.getUTCMonth() + 1)}-${pad2(day.getUTCDate())}`;
}

function monthKey(day: Date): string {
  return `${day.getUTCFullYear()}-${pad2(day.getUTCMonth() + 1)}`;
}

function monthStart(year: number, monthIndex: number): Date {
  return new Date(Date.UTC(year, monthIndex, 1));
}

function monthEnd(year: number, monthIndex: number): Date {
  return new Date(Date.UTC(year, monthIndex + 1, 0));
}

function monthLabel(first: Date): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(first);
}

/** Current UTC month (month-to-date) plus the previous 12 complete months. */
export function usageMonths(now = new Date()): UsageMonth[] {
  const today = utcCalendarDay(now);
  const out: UsageMonth[] = [];
  for (let ago = 0; ago <= USAGE_MONTH_LOOKBACK; ago += 1) {
    const first = monthStart(today.getUTCFullYear(), today.getUTCMonth() - ago);
    const isCurrent = ago === 0;
    const last = isCurrent
      ? today
      : monthEnd(first.getUTCFullYear(), first.getUTCMonth());
    const label = monthLabel(first);
    out.push({
      key: monthKey(first),
      from: isoDay(first),
      to: isoDay(last),
      label: isCurrent ? `${label} (so far)` : label,
      isCurrent,
    });
  }
  return out;
}

export function defaultOpenRouterUsageMonth(now = new Date()): UsageMonth {
  return usageMonths(now)[0]!;
}

/** Last complete UTC month — the period an AWS invoice covers. */
export function defaultAwsUsageMonth(now = new Date()): UsageMonth {
  const months = usageMonths(now);
  return months[1] ?? months[0]!;
}

export function findUsageMonth(
  months: readonly UsageMonth[],
  key: string,
): UsageMonth | undefined {
  return months.find((row) => row.key === key);
}

export function usageRangeQuery(fromDay: string, toDay: string): string {
  const params = new URLSearchParams();
  params.set("from", fromDay);
  params.set("to", toDay);
  return `?${params.toString()}`;
}
