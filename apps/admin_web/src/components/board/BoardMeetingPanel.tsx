import { useState } from "react";
import { DateTimeDisplay } from "../ui";
import { BoardMinutesView } from "./BoardMinutesView";
import { BoardTranscript } from "./BoardTranscript";
import {
  formatTokens,
  formatUsageCost,
  uniqueTurnModels,
  MEETING_MODE_LABELS,
  MEETING_STATUS_BADGE_CLASS,
  meetingPhaseProgress,
  memberLabel,
  type BoardMember,
} from "../../lib/boardModel";
import type { MeetingWithTurns } from "../../hooks/useBoardMeetings";

export type BoardMeetingPanelProps = {
  readonly data: MeetingWithTurns | undefined;
  readonly isLoading: boolean;
  readonly members: readonly BoardMember[];
  readonly onCancel: (meetingId: string) => void;
  readonly isCancelling: boolean;
  readonly onClose: () => void;
  readonly onOpenApproval?: (approvalId: string) => void;
};

type View = "minutes" | "transcript";

export function BoardMeetingPanel({ data, isLoading, members, onCancel, isCancelling, onClose, onOpenApproval }: BoardMeetingPanelProps) {
  const [view, setView] = useState<View>("minutes");

  if (isLoading || !data) {
    return (
      <div className="card shadow-sm mb-4">
        <div className="card-body text-muted small">Loading meeting…</div>
      </div>
    );
  }

  const { meeting, turns } = data;
  const isRunning = meeting.status === "running";
  const progress = meetingPhaseProgress(meeting);
  const activeView: View = meeting.minutes && !isRunning ? view : "transcript";
  const servedModels = uniqueTurnModels(turns);
  const configuredModels = Object.values(meeting.models).filter(Boolean);
  const roster = meeting.roster.length > 0
    ? meeting.roster.map((r) => ({ id: r.id, displayName: r.displayName, shortName: r.id.toUpperCase() }))
    : members;

  return (
    <div className="card shadow-sm mb-4">
      <div className="card-body">
        <div className="d-flex flex-wrap justify-content-between align-items-start gap-2 mb-2">
          <div>
            <div className="d-flex align-items-center gap-2 flex-wrap">
              <span className={`badge ${MEETING_STATUS_BADGE_CLASS[meeting.status]}`}>{meeting.status}</span>
              <span className="fw-semibold">{MEETING_MODE_LABELS[meeting.mode]}</span>
              {meeting.topic ? <span className="text-muted">· {meeting.topic}</span> : null}
            </div>
            <div className="small text-muted">
              <DateTimeDisplay iso={meeting.createdAt} /> · chaired by {memberLabel(roster, meeting.chair)} ·{" "}
              {meeting.trigger.startsWith("schedule") ? "scheduled" : "started by you"} ·{" "}
              {formatUsageCost(meeting.usage?.cost)} · {formatTokens(meeting.usage?.totalTokens)}
            </div>
          </div>
          <div className="d-flex gap-2">
            {isRunning ? (
              <button type="button" className="btn btn-sm btn-outline-danger" disabled={isCancelling} onClick={() => onCancel(meeting.meetingId)}>
                {isCancelling ? "Cancelling…" : "Cancel meeting"}
              </button>
            ) : null}
            <button type="button" className="btn btn-sm btn-outline-secondary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        {isRunning ? (
          <div className="mb-3">
            <div className="d-flex justify-content-between small text-muted mb-1">
              <span>{progress.label}</span>
              <span>step {progress.index + 1} of {progress.total}</span>
            </div>
            <div className="progress" style={{ height: 6 }} aria-hidden="true">
              <div className="progress-bar progress-bar-striped progress-bar-animated" style={{ width: `${progress.percent}%` }} />
            </div>
          </div>
        ) : null}

        {meeting.status === "failed" && meeting.errorMessage ? (
          <div className="alert alert-danger py-2 small">{meeting.errorMessage}</div>
        ) : null}

        {meeting.agenda.length > 0 ? (
          <details className="mb-3" open={isRunning}>
            <summary className="small text-uppercase text-muted fw-semibold">Agenda</summary>
            <ol className="small mb-0 mt-2 ps-3">
              {meeting.agenda.map((item, i) => (
                <li key={i}>
                  <span className="fw-semibold">{item.title}</span> — {item.question}
                  {item.whyNow ? <span className="text-muted"> ({item.whyNow})</span> : null}
                </li>
              ))}
            </ol>
          </details>
        ) : null}

        {meeting.minutes && !isRunning ? (
          <ul className="nav nav-pills mb-3 small">
            <li className="nav-item">
              <button type="button" className={`nav-link py-1 ${activeView === "minutes" ? "active" : ""}`} onClick={() => setView("minutes")}>Minutes</button>
            </li>
            <li className="nav-item">
              <button type="button" className={`nav-link py-1 ${activeView === "transcript" ? "active" : ""}`} onClick={() => setView("transcript")}>
                Transcript ({turns.length})
              </button>
            </li>
          </ul>
        ) : null}

        {activeView === "minutes" && meeting.minutes ? (
          <BoardMinutesView
            minutes={meeting.minutes}
            members={roster}
            createdActionCount={meeting.createdActionIds.length}
            reaffirmedActionCount={meeting.reaffirmedActionIds.length}
          />
        ) : (
          <BoardTranscript turns={turns} isRunning={isRunning} currentPhaseLabel={progress.label} onOpenApproval={onOpenApproval} />
        )}

        {meeting.contextPackHash ? (
          <div className="small text-muted mt-3 border-top pt-2">
            Context pack {meeting.contextPackHash} ({(meeting.contextPackChars ?? 0).toLocaleString()} chars) ·
            models {configuredModels.join(", ") || "default"}
            {servedModels.length ? ` · served ${servedModels.join(", ")}` : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
