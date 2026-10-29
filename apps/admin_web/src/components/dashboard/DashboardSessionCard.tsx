export function DashboardSessionCard({
  isLoading,
  isError,
  sub,
  email,
}: {
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly sub: string | undefined;
  readonly email: string | undefined;
}) {
  return (
    <div className="card h-100 shadow-sm">
      <div className="card-body d-flex flex-column">
        <h2 className="h6 mb-3">
          <strong>Session</strong>
        </h2>
        {isLoading ? (
          <p className="mb-0 small text-muted">Loading profile…</p>
        ) : isError ? (
          <p className="mb-0 small text-danger">
            Could not load profile. Check API configuration and sign-in.
          </p>
        ) : (
          <dl className="row small mb-0">
            <dt className="col-sm-5 text-muted">Subject</dt>
            <dd className="col-sm-7 text-end mb-0">{sub ?? "—"}</dd>
            <dt className="col-sm-5 text-muted pt-2">Email</dt>
            <dd className="col-sm-7 text-end pt-2 mb-0">{email ?? "—"}</dd>
          </dl>
        )}
      </div>
    </div>
  );
}
