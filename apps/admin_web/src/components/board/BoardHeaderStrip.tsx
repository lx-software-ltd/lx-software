import { AdminKpi, DateTimeDisplay } from "../ui";
import {
  formatUsageCost,
  meetingPhaseProgress,
  MEETING_MODE_LABELS,
  type BoardOverview,
} from "../../lib/boardModel";

export type BoardHeaderStripProps = {
  readonly overview: BoardOverview;
  readonly onRunStandup: () => void;
  readonly onPlanDeepDive: () => void;
  readonly onOpenMeeting: (meetingId: string) => void;
  readonly isStarting: boolean;
  readonly startError?: string | null;
};

export function BoardHeaderStrip({
  overview,
  onRunStandup,
  onPlanDeepDive,
  onOpenMeeting,
  isStarting,
  startError,
}: BoardHeaderStripProps) {
  const running = overview.runningMeeting;
  const latest = overview.latestMeeting;
  const usage = overview.usageToday;
  const isBudgetOut = usage.budgetUsd > 0 && usage.cost >= usage.budgetUsd;
  const actionsDisabled = isStarting || Boolean(running) || isBudgetOut;

  return (
    <div className="mb-4">
      <div className="d-flex flex-wrap align-items-start justify-content-between gap-3">
        <div className="admin-kpi-row flex-grow-1 mb-0">
          <MeetingTile
            running={running}
            latest={latest}
            onOpenMeeting={onOpenMeeting}
          />
          <AdminKpi label="Open actions" value={String(overview.openActionCount)} />
          <AdminKpi
            label="Spend today"
            value={
              <span className={isBudgetOut ? "text-danger" : undefined}>
                {formatUsageCost(usage.cost)}
              </span>
            }
            hint={`of ${formatUsageCost(usage.budgetUsd)}`}
          />
        </div>
        <div className="d-grid gap-2">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={onRunStandup}
            disabled={actionsDisabled}
          >
            {isStarting ? "Starting…" : "Run stand-up"}
          </button>
          <button
            type="button"
            className="btn btn-outline-secondary btn-sm"
            onClick={onPlanDeepDive}
            disabled={actionsDisabled}
          >
            Deep dive…
          </button>
        </div>
      </div>
      {startError ? <div className="alert alert-danger py-2 mt-3 mb-0 small">{startError}</div> : null}
    </div>
  );
}

function MeetingTile({
  running,
  latest,
  onOpenMeeting,
}: {
  readonly running: BoardOverview["runningMeeting"];
  readonly latest: BoardOverview["latestMeeting"];
  readonly onOpenMeeting: (meetingId: string) => void;
}) {
  if (running) {
    const progress = meetingPhaseProgress(running);
    return (
      <div className="admin-kpi">
        <div className="admin-kpi-label">Meeting in progress</div>
        <div className="admin-kpi-value">{MEETING_MODE_LABELS[running.mode]}</div>
        <div className="admin-kpi-hint">{progress.label}</div>
        <div className="progress mt-2" style={{ height: 4 }} aria-hidden="true">
          <div className="progress-bar" style={{ width: `${progress.percent}%` }} />
        </div>
        <button
          type="button"
          className="btn btn-sm btn-link px-0 mt-1"
          onClick={() => onOpenMeeting(running.meetingId)}
        >
          Watch the meeting
        </button>
      </div>
    );
  }
  if (latest) {
    return (
      <div className="admin-kpi">
        <div className="admin-kpi-label">Latest meeting</div>
        <div className="admin-kpi-value">{latest.headline || MEETING_MODE_LABELS[latest.mode]}</div>
        <div className="admin-kpi-hint">
          <DateTimeDisplay iso={latest.createdAt} /> · {latest.actionCount} action
          {latest.actionCount === 1 ? "" : "s"} · {formatUsageCost(latest.usage?.cost)}
        </div>
        <button
          type="button"
          className="btn btn-sm btn-link px-0 mt-1"
          onClick={() => onOpenMeeting(latest.meetingId)}
        >
          Read the minutes
        </button>
      </div>
    );
  }
  return (
    <AdminKpi
      label="Latest meeting"
      value="None yet"
      hint="Write the company brief, then run the first stand-up."
    />
  );
}
