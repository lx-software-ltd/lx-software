import { useMemo, useState } from "react";
import {
  findUsageMonth,
  usageMonths,
  type UsageMonth,
} from "../lib/usageMonth";

export function useUsageMonth(defaultMonth: (now?: Date) => UsageMonth) {
  const months = useMemo(() => usageMonths(), []);
  const [monthKey, setMonthKey] = useState(() => defaultMonth().key);
  const month = findUsageMonth(months, monthKey) ?? months[0] ?? defaultMonth();
  return { months, month, setMonthKey };
}
