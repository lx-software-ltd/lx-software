export function DashboardApiHealthCard({
  isLoading,
  isError,
  status,
}: {
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly status: string | undefined;
}) {
  return (
    <div className="card h-100 shadow-sm">
      <div className="card-body d-flex flex-column">
        <h2 className="h6 mb-3">
          <strong>API health</strong>
        </h2>
        {isLoading ? (
          <p className="mb-0 small text-muted">Checking /health…</p>
        ) : isError ? (
          <p className="mb-0 small text-danger">Health check failed.</p>
        ) : (
          <dl className="row small mb-0">
            <dt className="col-sm-5 text-muted">Endpoint</dt>
            <dd className="col-sm-7 text-end mb-0">
              <code>/health</code>
            </dd>
            <dt className="col-sm-5 text-muted pt-2">Status</dt>
            <dd className="col-sm-7 text-end pt-2 mb-0 text-success">{status ?? "ok"}</dd>
          </dl>
        )}
      </div>
    </div>
  );
}
