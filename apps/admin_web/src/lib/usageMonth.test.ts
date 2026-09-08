import { describe, expect, it } from "vitest";
import {
  USAGE_MONTH_LOOKBACK,
  defaultAwsUsageMonth,
  defaultOpenRouterUsageMonth,
  usageMonths,
  usageRangeQuery,
} from "./usageMonth";

const SEPT_8_2026 = new Date(Date.UTC(2026, 8, 8));
const JAN_1_2026 = new Date(Date.UTC(2026, 0, 1));

describe("usageMonths", () => {
  it("lists current UTC month-to-date plus 12 complete months", () => {
    const months = usageMonths(SEPT_8_2026);
    expect(months).toHaveLength(USAGE_MONTH_LOOKBACK + 1);
    expect(months[0]).toEqual({
      key: "2026-09",
      from: "2026-09-01",
      to: "2026-09-08",
      label: "September 2026 (so far)",
      isCurrent: true,
    });
    expect(months[1]).toMatchObject({
      key: "2026-08",
      from: "2026-08-01",
      to: "2026-08-31",
      label: "August 2026",
      isCurrent: false,
    });
    expect(months[12]).toMatchObject({
      key: "2025-09",
      from: "2025-09-01",
      to: "2025-09-30",
      isCurrent: false,
    });
  });

  it("uses the first of the month as month-to-date end on day one", () => {
    const [current, previous] = usageMonths(JAN_1_2026);
    expect(current).toMatchObject({
      key: "2026-01",
      from: "2026-01-01",
      to: "2026-01-01",
      isCurrent: true,
    });
    expect(previous).toMatchObject({
      key: "2025-12",
      from: "2025-12-01",
      to: "2025-12-31",
    });
  });
});

describe("defaults", () => {
  it("defaults OpenRouter to the current UTC month", () => {
    expect(defaultOpenRouterUsageMonth(SEPT_8_2026).key).toBe("2026-09");
  });

  it("defaults AWS to the last complete UTC month", () => {
    expect(defaultAwsUsageMonth(SEPT_8_2026).key).toBe("2026-08");
  });
});

describe("usageRangeQuery", () => {
  it("always sends from and to", () => {
    expect(usageRangeQuery("2026-08-01", "2026-08-31")).toBe(
      "?from=2026-08-01&to=2026-08-31",
    );
  });
});
