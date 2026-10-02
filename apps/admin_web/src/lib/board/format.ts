import type {
  ApprovalEditField,
  BoardAction,
  BoardActionPriority,
  BoardApprovalPreview,
  BoardMailPreview,
  BoardMeetingMode,
  BoardMeetingStatus,
  BoardMeetingSummary,
  BoardPhishingPreview,
  BoardTurn,
} from "./types";


export function isMailPreview(preview: BoardApprovalPreview | undefined): preview is BoardMailPreview {
  return !!preview && "kind" in preview && preview.kind === "email";
}


export function isPhishingPreview(preview: BoardApprovalPreview | undefined): preview is BoardPhishingPreview {
  return !!preview && "kind" in preview && preview.kind === "phishing";
}


const APPROVAL_TEXT_FIELDS: readonly { key: string; label: string; multiline: boolean }[] = [
  { key: "subject", label: "Subject", multiline: false },
  { key: "title", label: "Title", multiline: false },
  { key: "body", label: "Body", multiline: true },
  { key: "text", label: "Message", multiline: true },
  { key: "message", label: "Message", multiline: true },
  { key: "detail", label: "Detail", multiline: true },
  { key: "note", label: "Note", multiline: true },
];


/** Owner-facing text fields to edit instead of raw JSON. */
export function approvalEditableFields(
  args: Readonly<Record<string, unknown>>,
  preview?: BoardApprovalPreview,
): ApprovalEditField[] {
  const fields: ApprovalEditField[] = [];
  const seen = new Set<string>();
  if (isMailPreview(preview) && "body" in args) {
    // Only offer a subject when the op actually takes one (mail_send). Replies and
    // forwards derive it from the thread, so an edit there would be silently dropped.
    if ("subject" in args) {
      fields.push({ key: "subject", label: "Subject", multiline: false, value: String(args.subject ?? "") });
      seen.add("subject");
    }
    // Seed from the owner-facing preview (real addresses), not the masked model text.
    fields.push({ key: "body", label: "Body", multiline: true, value: String(preview.text ?? args.body ?? "") });
    seen.add("body");
  }
  for (const spec of APPROVAL_TEXT_FIELDS) {
    if (seen.has(spec.key)) continue;
    if (!(spec.key in args) || typeof args[spec.key] !== "string") continue;
    fields.push({ ...spec, value: String(args[spec.key]) });
    seen.add(spec.key);
  }
  return fields;
}


export const MEETING_MODE_LABELS: Readonly<Record<BoardMeetingMode, string>> = {
  standup: "Stand-up",
  deepDive: "Deep dive",
};


export const PRIORITY_LABELS: Readonly<Record<BoardActionPriority, string>> = {
  now: "Now",
  next: "Next",
  later: "Later",
};


export const PRIORITY_BADGE_CLASS: Readonly<Record<BoardActionPriority, string>> = {
  now: "text-bg-danger",
  next: "text-bg-warning",
  later: "text-bg-secondary",
};


export const PHASE_LABELS: Readonly<Record<string, string>> = {
  prepare: "Preparing context",
  agenda: "Chair drafts the agenda",
  positions: "Members give positions",
  challenge: "Chair challenges, members respond",
  synthesis: "Chair writes the minutes",
  persist: "Saving actions",
  done: "Done",
};


export const MEETING_STATUS_BADGE_CLASS: Readonly<Record<BoardMeetingStatus, string>> = {
  running: "text-bg-primary",
  succeeded: "text-bg-success",
  failed: "text-bg-danger",
  cancelled: "text-bg-secondary",
};


export function groupActionsByPriority(
  actions: readonly BoardAction[],
): Readonly<Record<BoardActionPriority, readonly BoardAction[]>> {
  const out: Record<BoardActionPriority, BoardAction[]> = { now: [], next: [], later: [] };
  for (const a of actions) {
    const key: BoardActionPriority = a.priority in out ? a.priority : "later";
    out[key].push(a);
  }
  for (const key of Object.keys(out) as BoardActionPriority[]) {
    out[key].sort((a, b) => {
      const da = a.dueAt ?? "9999";
      const db = b.dueAt ?? "9999";
      if (da !== db) return da < db ? -1 : 1;
      return a.createdAt < b.createdAt ? -1 : a.createdAt > b.createdAt ? 1 : 0;
    });
  }
  return out;
}


export type MeetingProgress = {
  readonly index: number;
  readonly total: number;
  readonly percent: number;
  readonly label: string;
};


export function meetingPhaseProgress(
  meeting: Pick<BoardMeetingSummary, "phase" | "phases" | "status">,
): MeetingProgress {
  const phases = meeting.phases.length > 0 ? meeting.phases : ["prepare", "agenda", "positions", "synthesis", "persist"];
  if (meeting.status !== "running") {
    return {
      index: phases.length,
      total: phases.length,
      percent: 100,
      label: PHASE_LABELS[meeting.status === "succeeded" ? "done" : meeting.phase] ?? meeting.status,
    };
  }
  const idx = Math.max(0, phases.indexOf(meeting.phase));
  return {
    index: idx,
    total: phases.length,
    percent: Math.round(((idx + 0.5) / phases.length) * 100),
    label: PHASE_LABELS[meeting.phase] ?? meeting.phase,
  };
}


export function uniqueTurnModels(turns: readonly BoardTurn[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const turn of turns) {
    const slug = (turn.model || "").trim();
    if (!slug || seen.has(slug)) continue;
    seen.add(slug);
    out.push(slug);
  }
  return out;
}


export function formatUsageCost(usd: number | undefined | null): string {
  const value = typeof usd === "number" && Number.isFinite(usd) ? usd : 0;
  if (value === 0) return "USD 0.00";
  if (value < 0.01) return `USD ${value.toFixed(4)}`;
  return `USD ${value.toFixed(2)}`;
}


export function formatTokens(tokens: number | undefined | null): string {
  const value = typeof tokens === "number" && Number.isFinite(tokens) ? tokens : 0;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M tokens`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k tokens`;
  return `${value} tokens`;
}


export function formatRelativeDuration(iso: string | undefined | null, nowMs: number = Date.now()): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "—";
  const abs = Math.abs(then - nowMs);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (abs < minute) return "<1m";
  if (abs < hour) return `${Math.round(abs / minute)}m`;
  if (abs < day) return `${Math.round(abs / hour)}h`;
  return `${Math.round(abs / day)}d`;
}


export function formatRelativeTime(iso: string | undefined | null, nowMs: number = Date.now()): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "—";
  const duration = formatRelativeDuration(iso, nowMs);
  if (duration === "—") return "—";
  if (duration === "<1m") return "just now";
  return then >= nowMs ? `in ${duration}` : `${duration} ago`;
}


/** `hello@siutindei.com` → `hello@`; keeps full addresses from other domains. */
export function mailboxShortLabel(address: string, domain?: string): string {
  const at = address.indexOf("@");
  if (at < 0) return address;
  const host = address.slice(at + 1);
  return domain && host === domain ? `${address.slice(0, at)}@` : address;
}


export function formatMailBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}


/** Full address, `@domain` wildcard, or E.164 / 8–15 digit phone. */
export const MAIL_ALLOW_LIST_ENTRY_RE =
  /^(?:(?:[a-z0-9._%+-]+)?@[a-z0-9.-]+\.[a-z]{2,}|\+?\d{8,15})$/i;


/** One entry per line or comma; lower-cased, de-duplicated, blanks dropped. */
export function parseAllowListText(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(/[\n,;]+/)) {
    const entry = raw.replace(/\s+/g, "").toLowerCase();
    if (entry && !out.includes(entry)) out.push(entry);
  }
  return out;
}
