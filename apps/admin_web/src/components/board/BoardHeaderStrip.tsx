import type { ReactNode } from "react";
import { AdminKpi } from "../ui";
import { formatDateTimeHKT } from "../../lib/formatDisplay";
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
  const meetingActionsDisabled = isStarting || Boolean(running) || isBudgetOut;

  return (
    <div>
      <div className="admin-kpi-row">
        <MeetingTile running={running} latest={latest} />
        <AdminKpi label="Open actions" value={overview.openActionCount} />
        <AdminKpi
          label="Spend today"
          value={
            <span className={isBudgetOut ? "text-danger" : undefined}>
              {formatUsageCost(usage.cost)} / {formatUsageCost(usage.budgetUsd)}
            </span>
          }
          hint={isBudgetOut ? "Over the daily budget" : "Daily budget"}
        />
      </div>
      <div className="admin-page-actions mb-4">
        {running ? (
          <button type="button" className="btn btn-outline-primary" onClick={() => onOpenMeeting(running.meetingId)}>
            Watch the meeting
          </button>
        ) : latest ? (
          <button type="button" className="btn btn-outline-primary" onClick={() => onOpenMeeting(latest.meetingId)}>
            Read the minutes
          </button>
        ) : null}
        <button type="button" className="btn btn-primary" onClick={onRunStandup} disabled={meetingActionsDisabled}>
          {isStarting ? "Starting…" : "Run stand-up"}
        </button>
        <button type="button" className="btn btn-outline-secondary" onClick={onPlanDeepDive} disabled={meetingActionsDisabled}>
          Deep dive…
        </button>
      </div>
      {startError ? <div className="alert alert-danger py-2 mb-4 small">{startError}</div> : null}
    </div>
  );
}

function MeetingTile({
  running,
  latest,
}: {
  readonly running: BoardOverview["runningMeeting"];
  readonly latest: BoardOverview["latestMeeting"];
}): ReactNode {
  if (running) {
    return (
      <AdminKpi
        label="Meeting"
        value={`${MEETING_MODE_LABELS[running.mode]} in progress`}
        hint={meetingPhaseProgress(running).label}
      />
    );
  }
  if (latest) {
    const actions = `${latest.actionCount} action${latest.actionCount === 1 ? "" : "s"}`;
    return (
      <AdminKpi
        label="Latest meeting"
        value={latest.headline || `${MEETING_MODE_LABELS[latest.mode]} meeting`}
        hint={`${formatDateTimeHKT(latest.createdAt)} · ${actions} · ${formatUsageCost(latest.usage?.cost)}`}
      />
    );
  }
  return <AdminKpi label="Meetings" value="None yet" />;
}
