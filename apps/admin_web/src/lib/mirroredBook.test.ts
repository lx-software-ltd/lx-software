import { describe, expect, it } from "vitest";
import { mirroredSyncIsPending, mirroredSyncTimedOut, type MirroredBookSummary } from "./mirroredBook";

const empty: MirroredBookSummary = {
  configured: true,
  syncedAt: null,
  lastAttemptAt: null,
  pendingSince: null,
  syncError: null,
  outstandingByCurrency: {},
  openInvoices: 0,
  submittedExpenses: 0,
  paidExpenses: 0,
  skippedUnsupportedCurrency: 0,
  skippedIncomplete: 0,
};

describe("mirroredSyncIsPending", () => {
  it("is false when nothing is in flight", () => {
    expect(mirroredSyncIsPending(undefined)).toBe(false);
    expect(mirroredSyncIsPending(empty)).toBe(false);
  });

  it("is true while pendingSince is set", () => {
    expect(mirroredSyncIsPending({ ...empty, pendingSince: "2026-10-02T03:00:00.000Z" })).toBe(true);
  });
});

describe("mirroredSyncTimedOut", () => {
  it("is false until two minutes have passed", () => {
    const pendingSince = "2026-10-02T03:00:00.000Z";
    const start = Date.parse(pendingSince);
    expect(mirroredSyncTimedOut({ ...empty, pendingSince }, start + 119_000)).toBe(false);
    expect(mirroredSyncTimedOut({ ...empty, pendingSince }, start + 120_000)).toBe(true);
    expect(mirroredSyncTimedOut(empty, start + 120_000)).toBe(false);
  });
});
