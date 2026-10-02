import { describe, expect, it } from "vitest";
import { compareStatementLinesNewestFirst } from "./statementLineSort";

describe("compareStatementLinesNewestFirst", () => {
  it("orders by document date, so a backdated invoice created later still sits with its year", () => {
    const backdated = { id: "es-inv-b", dateUtc: "2025-03-01T00:00:00.000Z" };
    const recent = { id: "es-inv-a", dateUtc: "2026-09-15T00:00:00.000Z" };
    expect([backdated, recent].sort(compareStatementLinesNewestFirst)).toEqual([recent, backdated]);
  });

  it("breaks a date tie by id", () => {
    const a = { id: "es-inv-a", dateUtc: "2026-05-02T00:00:00.000Z" };
    const b = { id: "es-inv-b", dateUtc: "2026-05-02T00:00:00.000Z" };
    expect([b, a].sort(compareStatementLinesNewestFirst)).toEqual([a, b]);
  });
});
