import {
  BOARD_PERSONA_DEFAULTS,
  BOARD_STAFF_MAX_STEPS_PER_TASK,
  BOARD_STAFF_SEAT_DEFAULTS,
  type BoardTaskStatus,
} from "../contracts/generated";
import { formatRelativeDuration, formatRelativeTime } from "./format";
import type {
  BoardSeat,
  BoardTask,
  } from "./types";


export function canRetryBoardTask(status: string): boolean {
  return status === "failed" || status === "needs_owner";
}


export const TASK_ID_SHORT_LENGTH = 8;

export const TASK_SLA_SOON_MS = 6 * 60 * 60 * 1000;

export const TASK_DONE_LANE_PREVIEW = 5;


export function shortTaskId(taskId: string): string {
  const id = taskId.trim();
  return id.length <= TASK_ID_SHORT_LENGTH ? id : id.slice(0, TASK_ID_SHORT_LENGTH);
}


export function isFinishedBoardTaskStatus(status: string): boolean {
  return status === "delivered" || status === "cancelled";
}


export type BoardTaskLaneId = "attention" | "in_progress" | "done";


const ATTENTION_STATUSES = ["needs_owner", "review"] as const satisfies readonly BoardTaskStatus[];

const IN_PROGRESS_STATUSES = [
  "running",
  "waiting_approval",
  "waiting_subtask",
  "queued",
  "awaiting_import",
] as const satisfies readonly BoardTaskStatus[];

const DONE_STATUSES = ["failed", "delivered", "cancelled"] as const satisfies readonly BoardTaskStatus[];


export const BOARD_TASK_LANES: readonly {
  readonly id: BoardTaskLaneId;
  readonly label: string;
  readonly empty: string;
  readonly statuses: readonly BoardTaskStatus[];
}[] = [
  {
    id: "attention",
    label: "Attention",
    empty: "Nothing waiting on you",
    statuses: ATTENTION_STATUSES,
  },
  {
    id: "in_progress",
    label: "In progress",
    empty: "Nothing running or queued",
    statuses: IN_PROGRESS_STATUSES,
  },
  {
    id: "done",
    label: "Done",
    empty: "No finished tasks",
    statuses: DONE_STATUSES,
  },
];


const LANE_BY_STATUS: Readonly<Record<string, BoardTaskLaneId>> = Object.fromEntries(
  BOARD_TASK_LANES.flatMap((lane) => lane.statuses.map((status) => [status, lane.id])),
);


export function taskLane(status: string): BoardTaskLaneId | null {
  return LANE_BY_STATUS[status] ?? null;
}


export type BoardTaskStatusTone = "warning" | "primary" | "info" | "secondary" | "success" | "danger";


export const BOARD_TASK_STATUS_META: readonly {
  readonly id: BoardTaskStatus;
  readonly label: string;
  readonly tone: BoardTaskStatusTone;
}[] = [
  { id: "needs_owner", label: "Needs owner", tone: "warning" },
  { id: "review", label: "Review", tone: "primary" },
  { id: "waiting_approval", label: "Waiting approval", tone: "info" },
  { id: "waiting_subtask", label: "Waiting help", tone: "info" },
  { id: "running", label: "Running", tone: "primary" },
  { id: "queued", label: "Queued", tone: "secondary" },
  { id: "awaiting_import", label: "To import", tone: "info" },
  { id: "delivered", label: "Delivered", tone: "success" },
  { id: "failed", label: "Failed", tone: "danger" },
  { id: "cancelled", label: "Cancelled", tone: "secondary" },
];


const STATUS_META_BY_ID = Object.fromEntries(BOARD_TASK_STATUS_META.map((row) => [row.id, row]));


export function taskStatusLabel(status: string): string {
  return STATUS_META_BY_ID[status]?.label ?? status.replace(/_/g, " ");
}


export function taskStatusTone(status: string): BoardTaskStatusTone {
  return STATUS_META_BY_ID[status]?.tone ?? "secondary";
}


export type BoardTaskSlaState = "none" | "ok" | "soon" | "overdue";


export function taskSlaState(
  slaAt: string | undefined | null,
  nowMs: number = Date.now(),
  status?: string,
): BoardTaskSlaState {
  if (status === "awaiting_import" || status === "failed" || isFinishedBoardTaskStatus(status ?? "")) {
    return "none";
  }
  if (!slaAt) return "none";
  const at = Date.parse(slaAt);
  if (!Number.isFinite(at)) return "none";
  if (at < nowMs) return "overdue";
  if (at - nowMs <= TASK_SLA_SOON_MS) return "soon";
  return "ok";
}


export function taskSlaLabel(slaAt: string | undefined | null, nowMs: number = Date.now(), status?: string): string {
  const sla = taskSlaState(slaAt, nowMs, status);
  if (sla === "none") return "No SLA";
  if (sla === "overdue") return `Overdue ${formatRelativeDuration(slaAt, nowMs)}`;
  return `SLA ${formatRelativeTime(slaAt, nowMs)}`;
}


export function taskActorLabel(
  id: string,
  seats: readonly Pick<BoardSeat, "id" | "displayName">[] = [],
): string {
  const seat = seats.find((s) => s.id === id);
  if (seat?.displayName) return seat.displayName;
  const staffDefault = BOARD_STAFF_SEAT_DEFAULTS.find((s) => s.id === id);
  if (staffDefault) return staffDefault.title;
  const persona = BOARD_PERSONA_DEFAULTS.find((p) => p.id === id);
  if (persona) return persona.shortName;
  return id;
}


export function taskStepsLimit(): number {
  return BOARD_STAFF_MAX_STEPS_PER_TASK;
}


export function sumTaskUsageCost(tasks: readonly Pick<BoardTask, "usage">[]): number {
  return tasks.reduce((sum, task) => sum + (Number(task.usage?.cost) || 0), 0);
}


export function filterBoardTasks(
  tasks: readonly BoardTask[],
  opts: {
    query?: string;
    assignee?: string;
    status?: string;
    includeFinished?: boolean;
    actorLabel?: (id: string) => string;
  } = {},
): BoardTask[] {
  const query = (opts.query ?? "").trim().toLowerCase();
  const assignee = opts.assignee ?? "";
  const status = opts.status ?? "";
  return tasks.filter((task) => {
    if (!opts.includeFinished && isFinishedBoardTaskStatus(task.status)) return false;
    if (assignee && task.assignee !== assignee) return false;
    if (status && task.status !== status) return false;
    if (!query) return true;
    const actor = opts.actorLabel?.(task.assignee) ?? taskActorLabel(task.assignee);
    const hay = [
      task.taskId,
      shortTaskId(task.taskId),
      `#${shortTaskId(task.taskId)}`,
      task.brief,
      task.assignee,
      actor,
      task.failureReason ?? "",
      task.summary ?? "",
      task.parentTaskId ?? "",
      ...(task.helpTaskIds ?? []),
    ]
      .join("\n")
      .toLowerCase();
    return hay.includes(query);
  });
}


function cmpIso(a: string | undefined | null, b: string | undefined | null, dir: "asc" | "desc"): number {
  const left = a || "";
  const right = b || "";
  const raw = left.localeCompare(right);
  return dir === "desc" ? -raw : raw;
}


function statusOrder(status: string, order: readonly string[]): number {
  const index = order.indexOf(status);
  return index < 0 ? order.length : index;
}


function inProgressTimeCmp(a: BoardTask, b: BoardTask): number {
  if (a.status === "queued") return cmpIso(a.slaAt, b.slaAt, "asc");
  if (a.status === "awaiting_import") {
    return cmpIso(a.acceptedAt || a.updatedAt, b.acceptedAt || b.updatedAt, "asc");
  }
  return cmpIso(
    a.startedAt || a.parkedAt || a.updatedAt,
    b.startedAt || b.parkedAt || b.updatedAt,
    "desc",
  );
}


export function sortTasksInLane(lane: BoardTaskLaneId, tasks: readonly BoardTask[]): BoardTask[] {
  const copy = [...tasks];
  if (lane === "attention") {
    copy.sort(
      (a, b) =>
        statusOrder(a.status, ATTENTION_STATUSES) - statusOrder(b.status, ATTENTION_STATUSES) ||
        cmpIso(a.updatedAt, b.updatedAt, "desc") ||
        a.taskId.localeCompare(b.taskId),
    );
  } else if (lane === "in_progress") {
    copy.sort(
      (a, b) =>
        statusOrder(a.status, IN_PROGRESS_STATUSES) - statusOrder(b.status, IN_PROGRESS_STATUSES) ||
        inProgressTimeCmp(a, b) ||
        a.taskId.localeCompare(b.taskId),
    );
  } else {
    copy.sort(
      (a, b) =>
        Number(b.status === "failed") - Number(a.status === "failed") ||
        cmpIso(a.finishedAt || a.updatedAt, b.finishedAt || b.updatedAt, "desc") ||
        a.taskId.localeCompare(b.taskId),
    );
  }
  return copy;
}


export function groupTasksByLane(tasks: readonly BoardTask[]): Record<BoardTaskLaneId, BoardTask[]> {
  const grouped: Record<BoardTaskLaneId, BoardTask[]> = {
    attention: [],
    in_progress: [],
    done: [],
  };
  for (const task of tasks) {
    const lane = taskLane(task.status);
    if (lane) grouped[lane].push(task);
  }
  (Object.keys(grouped) as BoardTaskLaneId[]).forEach((lane) => {
    grouped[lane] = sortTasksInLane(lane, grouped[lane]);
  });
  return grouped;
}


export function tasksNeedPolling(tasks: readonly BoardTask[]): boolean {
  return tasks.some(
    (t) =>
      t.status === "running" ||
      t.status === "review" ||
      t.status === "waiting_approval" ||
      t.status === "waiting_subtask",
  );
}
