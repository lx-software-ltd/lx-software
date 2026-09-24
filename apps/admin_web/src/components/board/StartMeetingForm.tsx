import { useState, type FormEvent } from "react";
import {
  MEETING_MODE_LABELS,
  memberLabel,
  type BoardMeetingMode,
  type BoardMember,
} from "../../lib/boardModel";
import { BOARD_MAX_TOPIC_LEN } from "../../lib/contracts/generated";
import type { StartMeetingVariables } from "../../hooks/useBoardMeetings";

export type StartMeetingFormProps = {
  readonly members: readonly BoardMember[];
  readonly defaultChair: string;
  readonly initialMode: BoardMeetingMode;
  readonly initialTopic?: string;
  readonly isStarting: boolean;
  readonly onStart: (vars: StartMeetingVariables) => void;
  readonly onCancel: () => void;
};

export function StartMeetingForm({
  members,
  defaultChair,
  initialMode,
  initialTopic = "",
  isStarting,
  onStart,
  onCancel,
}: StartMeetingFormProps) {
  const [mode, setMode] = useState<BoardMeetingMode>(initialMode);
  const [chair, setChair] = useState(defaultChair);
  const [topic, setTopic] = useState(initialTopic);
  const topicRequired = mode === "deepDive";
  const canStart = !isStarting && (!topicRequired || topic.trim().length > 0);

  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    if (!canStart) return;
    onStart({ mode, chair, topic: topic.trim() || undefined });
  };

  return (
    <form className="card shadow-sm mb-4" onSubmit={submit}>
      <div className="card-body">
        <h2 className="admin-card-title">Start a meeting</h2>
        <div className="row g-3">
          <div className="col-12 col-md-3">
            <label className="form-label" htmlFor="board-meeting-mode">Format</label>
            <select
              id="board-meeting-mode"
              className="form-select"
              value={mode}
              onChange={(ev) => setMode(ev.target.value as BoardMeetingMode)}
            >
              {(Object.keys(MEETING_MODE_LABELS) as BoardMeetingMode[]).map((m) => (
                <option key={m} value={m}>{MEETING_MODE_LABELS[m]}</option>
              ))}
            </select>
            <div className="form-text">
              {mode === "standup"
                ? "Three agenda items, every member speaks once, chair writes minutes."
                : "Topic-led; the chair challenges positions before writing minutes."}
            </div>
          </div>
          <div className="col-12 col-md-3">
            <label className="form-label" htmlFor="board-meeting-chair">Chair</label>
            <select
              id="board-meeting-chair"
              className="form-select"
              value={chair}
              onChange={(ev) => setChair(ev.target.value)}
            >
              {members.map((m) => (
                <option key={m.id} value={m.id}>{memberLabel(members, m.id)}</option>
              ))}
            </select>
          </div>
          <div className="col-12 col-md-6">
            <label className="form-label" htmlFor="board-meeting-topic">
              Topic {topicRequired ? "" : <span className="text-muted">(optional)</span>}
            </label>
            <input
              id="board-meeting-topic"
              className="form-control"
              value={topic}
              maxLength={BOARD_MAX_TOPIC_LEN}
              placeholder={topicRequired ? "What should the board dig into?" : "Steer today's agenda"}
              onChange={(ev) => setTopic(ev.target.value)}
              required={topicRequired}
            />
          </div>
        </div>
      </div>
      <div className="card-footer bg-transparent border-top d-flex gap-2">
        <button type="submit" className="btn btn-primary" disabled={!canStart}>
          {isStarting ? "Starting…" : `Start ${MEETING_MODE_LABELS[mode].toLowerCase()}`}
        </button>
        <button type="button" className="btn btn-outline-secondary" onClick={onCancel} disabled={isStarting}>
          Cancel
        </button>
      </div>
    </form>
  );
}
