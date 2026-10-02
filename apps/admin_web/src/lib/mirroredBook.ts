/** Last product-database snapshot for a mirrored statement book. */

export type MirroredBookSummary = {
  readonly configured: boolean;
  readonly syncedAt: string | null;
  readonly lastAttemptAt: string | null;
  readonly pendingSince: string | null;
  readonly syncError: string | null;
  readonly outstandingByCurrency: Readonly<Record<string, number>>;
  readonly openInvoices: number;
  readonly submittedExpenses: number;
  readonly paidExpenses: number;
  readonly skippedUnsupportedCurrency: number;
  readonly skippedIncomplete: number;
};

export type MirroredBookSyncResponse = MirroredBookSummary & {
  readonly ok?: boolean;
  readonly queued?: boolean;
  readonly invoked?: boolean;
  readonly requestedAt?: string;
  readonly skipped?: string;
};

export function mirroredSyncIsPending(summary: Pick<MirroredBookSummary, "pendingSince"> | undefined): boolean {
  return Boolean(summary?.pendingSince);
}

const SYNC_WAIT_MS = 120_000;

export function mirroredSyncTimedOut(
  summary: Pick<MirroredBookSummary, "pendingSince"> | undefined,
  nowMs: number = Date.now(),
): boolean {
  const started = Date.parse(summary?.pendingSince ?? "");
  return Number.isFinite(started) && nowMs - started >= SYNC_WAIT_MS;
}
