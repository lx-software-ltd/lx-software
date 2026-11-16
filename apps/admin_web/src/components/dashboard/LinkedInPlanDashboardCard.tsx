import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LINKEDIN_PLAN_KEY, linkedInPlanQuery } from "../../hooks/useLinkedIn";
import { formatDateTimeHKT } from "../../lib/formatDisplay";
import { linkedInPlanSummary } from "../../lib/linkedinModel";

/** setTimeout delays above this are clamped by the browser. */
const REFRESH_WAIT_MAX_MS = 24 * 60 * 60 * 1000;

export function LinkedInPlanDashboardCard() {
  const queryClient = useQueryClient();
  const plan = useQuery(linkedInPlanQuery());
  const summary = plan.data ? linkedInPlanSummary(plan.data) : null;
  const rawSlot = plan.data?.nextEmptySlot?.trim() ?? "";
  const askedRefresh = useRef<string | null>(null);

  useEffect(() => {
    const refreshAt = plan.data?.refreshAt;
    if (!refreshAt) return;
    const delay = new Date(refreshAt).getTime() - Date.now();
    if (!Number.isFinite(delay)) return;
    let timer = 0;
    const arm = () => {
      const remaining = new Date(refreshAt).getTime() - Date.now();
      if (!Number.isFinite(remaining)) return;
      if (remaining <= 0) {
        if (askedRefresh.current === refreshAt) return;
        askedRefresh.current = refreshAt;
        void queryClient.invalidateQueries({ queryKey: LINKEDIN_PLAN_KEY });
        return;
      }
      timer = window.setTimeout(arm, Math.min(remaining, REFRESH_WAIT_MAX_MS));
    };
    if (delay <= 0) {
      arm();
      return;
    }
    timer = window.setTimeout(arm, Math.min(delay, REFRESH_WAIT_MAX_MS));
    return () => window.clearTimeout(timer);
  }, [plan.data?.refreshAt, queryClient]);

  const slotLabel = summary?.nextEmptySlot
    ? formatDateTimeHKT(summary.nextEmptySlot)
    : rawSlot && plan.isFetching
      ? "Updating…"
      : "None in the next few months";

  return (
    <div className="card h-100 shadow-sm">
      <div className="card-body d-flex flex-column">
        <h2 className="h6 mb-3">
          <strong>LinkedIn</strong>
        </h2>
        {plan.isPending ? (
          <p className="mb-0 small text-muted">Loading LinkedIn plan…</p>
        ) : plan.isError || !summary ? (
          <p className="mb-0 small text-danger">Could not load the LinkedIn plan.</p>
        ) : (
          <>
            <dl className="small mb-0">
              <dt className="text-muted">Planned</dt>
              <dd className="mb-0 fs-4 fw-semibold lh-sm">{summary.planned}</dd>
              <dt className="text-muted pt-3">Overdue</dt>
              <dd className="mb-0">{summary.overdue}</dd>
              <dt className="text-muted pt-3">Next empty slot</dt>
              <dd className="mb-0">{slotLabel}</dd>
            </dl>
            <p className="text-muted small mb-0 mt-3">
              Planned posts are approved and their slot has not arrived. Overdue posts missed that
              time and are still not posted. The next empty slot is the first open time on the
              schedule.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
