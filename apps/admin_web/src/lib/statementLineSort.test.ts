import { describe, expect, it } from "vitest";
import { compareStatementLinesNewestFirst } from "./statementLineSort";

describe("compareStatementLinesNewestFirst", () => {
  it("orders by sortUtc so a backdated invoice still leads when created later", () => {
    const recent = {
      dateUtc: "2026-03-01T00:00:00.000Z",
      sortUtc: "2026-10-01T12:00:00.000Z",
    };
    const older = {
      dateUtc: "2026-09-15T00:00:00.000Z",
      sortUtc: "2026-09-16T00:00:00.000Z",
    };
    const byDate = new Date(older.dateUtc).getTime() - new Date(recent.dateUtc).getTime();
    expect(byDate).toBeGreaterThan(0);
    expect(compareStatementLinesNewestFirst(recent, older)).toBeLessThan(0);
    expect([recent, older].sort(compareStatementLinesNewestFirst)).toEqual([recent, older]);
  });

  it("falls back to dateUtc when sortUtc is missing", () => {
    const later = { dateUtc: "2026-10-02T00:00:00.000Z" };
    const earlier = { dateUtc: "2026-10-01T00:00:00.000Z" };
    expect([earlier, later].sort(compareStatementLinesNewestFirst)).toEqual([later, earlier]);
  });
});
