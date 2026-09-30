/** Last product-database snapshot for a mirrored statement book. */

export type MirroredBookSummary = {
  readonly configured: boolean;
  readonly syncedAt: string | null;
  readonly outstandingByCurrency: Readonly<Record<string, number>>;
  readonly openInvoices: number;
  readonly submittedExpenses: number;
  readonly paidExpenses: number;
  readonly skippedUnsupportedCurrency: number;
};
