import { useQuery } from "@tanstack/react-query";
import { LINKEDIN_KEY } from "../../hooks/useLinkedIn";
import { adminFetchJson } from "../../lib/apiAdminClient";
import { formatDateTimeHKT } from "../../lib/formatDisplay";
import { linkedInPlanSummary, type LinkedInOverview } from "../../lib/linkedinModel";

export function LinkedInPlanDashboardCard() {
  const overview = useQuery({
    queryKey: [...LINKEDIN_KEY, "overview"] as const,
    queryFn: () => adminFetchJson<LinkedInOverview>("/lx-software/linkedin"),
  });
  const summary = overview.data ? linkedInPlanSummary(overview.data) : null;

  return (
    <div className="card h-100 shadow-sm">
      <div className="card-body d-flex flex-column">
        <h2 className="h6 mb-3">
          <strong>LinkedIn</strong>
        </h2>
        {overview.isPending ? (
          <p className="mb-0 small text-muted">Loading LinkedIn plan…</p>
        ) : overview.isError || !summary ? (
          <p className="mb-0 small text-danger">Could not load the LinkedIn plan.</p>
        ) : (
          <>
            <dl className="small mb-0">
              <dt className="text-muted">Planned</dt>
              <dd className="mb-0 fs-4 fw-semibold lh-sm">{summary.planned}</dd>
              <dt className="text-muted pt-3">Next empty slot</dt>
              <dd className="mb-0">
                {summary.nextEmptySlot
                  ? formatDateTimeHKT(summary.nextEmptySlot)
                  : "None in the next few months"}
              </dd>
            </dl>
            <p className="text-muted small mb-0 mt-3">
              Planned posts are approved and waiting for their slot. The next empty slot is the
              first open time on the schedule.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
