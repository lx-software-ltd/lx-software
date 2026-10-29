type FinanceDataLoadOrErrorProps = {
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly loadingMessage?: string;
  readonly loadErrorMessage?: string;
  /** When provided, the error alert offers a Retry button that re-runs the query. */
  readonly onRetry?: () => void;
  readonly isRetrying?: boolean;
};

/** Loading line or danger alert when the finance query fails. */
export function FinanceDataLoadOrError({
  isLoading,
  isError,
  loadingMessage = "Loading finance data…",
  loadErrorMessage = "Could not load finance data. Check API configuration and sign-in.",
  onRetry,
  isRetrying = false,
}: FinanceDataLoadOrErrorProps) {
  if (isLoading) {
    return <p className="text-muted small mb-3">{loadingMessage}</p>;
  }
  if (isError) {
    return (
      <div
        className="alert alert-danger py-2 small mb-3 d-flex flex-wrap align-items-center gap-2"
        role="alert"
      >
        <span className="flex-grow-1">{loadErrorMessage}</span>
        {onRetry ? (
          <button
            type="button"
            className="btn btn-sm btn-outline-danger"
            onClick={onRetry}
            disabled={isRetrying}
          >
            {isRetrying ? "Retrying…" : "Retry"}
          </button>
        ) : null}
      </div>
    );
  }
  return null;
}

type FinanceSaveStatusProps = {
  readonly isSaving: boolean;
  readonly saveError: unknown;
  readonly saveErrorDetail: string | null | undefined;
};

/** Warning when a finance mutation fails, plus optional saving line. */
export function FinanceSaveStatus({
  isSaving,
  saveError,
  saveErrorDetail,
}: FinanceSaveStatusProps) {
  return (
    <>
      {saveError ? (
        <div className="alert alert-warning py-2 small mb-3" role="alert">
          <span className="fw-semibold">Could not save changes.</span>{" "}
          {saveErrorDetail ?? "Try again or refresh the page."}
        </div>
      ) : null}
      {isSaving ? <p className="text-muted small mb-3">Saving…</p> : null}
    </>
  );
}
