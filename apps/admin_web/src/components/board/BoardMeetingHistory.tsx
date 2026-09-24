import { useMemo, useState } from "react";
import {
  AdminCell,
  AdminDataTable,
  AdminDataTableCellMeta,
  AdminDataTableEmptyRow,
  AdminRowActions,
  DateTimeDisplay,
} from "../ui";
import {
  formatUsageCost,
  MEETING_MODE_LABELS,
  MEETING_STATUS_BADGE_CLASS,
  memberLabel,
  type BoardMeetingSummary,
  type BoardMember,
} from "../../lib/boardModel";

export type BoardMeetingHistoryProps = {
  readonly meetings: readonly BoardMeetingSummary[];
  readonly members: readonly BoardMember[];
  readonly selectedMeetingId: string | null;
  readonly onOpen: (meetingId: string) => void;
};

const COLUMNS = [
  { key: "when", header: "When", priority: "secondary" as const },
  { key: "format", header: "Format", priority: "tertiary" as const },
  { key: "headline", header: "Headline" },
  { key: "actions", header: "Actions", className: "text-end", priority: "secondary" as const },
  { key: "cost", header: "Cost", className: "text-end", priority: "tertiary" as const },
  { key: "status", header: "Status", priority: "secondary" as const },
  { key: "ops", header: <span className="visually-hidden">Operations</span>, className: "text-end" },
] as const;

export function BoardMeetingHistory({ meetings, members, selectedMeetingId, onOpen }: BoardMeetingHistoryProps) {
  const [filter, setFilter] = useState("");
  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return meetings;
    return meetings.filter((m) =>
      [m.headline, m.topic, m.mode, m.status, memberLabel(members, m.chair)].join(" ").toLowerCase().includes(q),
    );
  }, [meetings, members, filter]);

  return (
    <AdminDataTable columns={COLUMNS} filterValue={filter} onFilterChange={setFilter} filterPlaceholder="Filter meetings…">
      {rows.length === 0 ? (
        <AdminDataTableEmptyRow colSpan={COLUMNS.length} message="No meetings yet." />
      ) : (
        rows.map((m) => (
          <tr key={m.meetingId} className={m.meetingId === selectedMeetingId ? "table-active" : ""}>
            <AdminCell column="when"><DateTimeDisplay iso={m.createdAt} /></AdminCell>
            <AdminCell column="format">
              {MEETING_MODE_LABELS[m.mode]}
              {m.trigger.startsWith("schedule") ? <span className="badge text-bg-light border ms-1">auto</span> : null}
            </AdminCell>
            <AdminCell column="headline" className="board-clamp-1">
              {m.headline || m.topic || <span className="text-muted">—</span>}
              <AdminDataTableCellMeta>
                <DateTimeDisplay iso={m.createdAt} className="text-muted" /> ·{" "}
                <span className={`badge ${MEETING_STATUS_BADGE_CLASS[m.status]}`}>{m.status}</span>
                {m.actionCount > 0 ? ` · ${m.actionCount} action${m.actionCount === 1 ? "" : "s"}` : ""}
              </AdminDataTableCellMeta>
              <AdminDataTableCellMeta until="tertiary">
                {MEETING_MODE_LABELS[m.mode]}
                {m.trigger.startsWith("schedule") ? " · auto" : ""} · {formatUsageCost(m.usage?.cost)}
              </AdminDataTableCellMeta>
            </AdminCell>
            <AdminCell column="actions" className="text-end">{m.actionCount}</AdminCell>
            <AdminCell column="cost" className="text-end">{formatUsageCost(m.usage?.cost)}</AdminCell>
            <AdminCell column="status"><span className={`badge ${MEETING_STATUS_BADGE_CLASS[m.status]}`}>{m.status}</span></AdminCell>
            <AdminCell column="ops" className="text-end">
              <AdminRowActions
                actions={[
                  {
                    id: "open",
                    label: "Open meeting",
                    iconClassName: "bi bi-journal-text",
                    onClick: () => onOpen(m.meetingId),
                  },
                ]}
              />
            </AdminCell>
          </tr>
        ))
      )}
    </AdminDataTable>
  );
}
