import {
  BOARD_PERSONA_DEFAULTS,
  BOARD_TOOL_DEFINITIONS,
  BOARD_TOOL_LEVELS,
  type BoardActionPriority,
  type BoardActionStatus,
  type BoardActionClass,
  type BoardDeliverableType,
  type BoardHoldStatus,
  type BoardMeetingMode,
  type BoardStaffModelTier,
  type BoardTaskOrigin,
  type BoardTaskStatus,
  type BoardToolGlobalMode,
  type BoardToolLevel,
} from "./contracts/generated";

export type {
  BoardActionClass,
  BoardActionPriority,
  BoardActionStatus,
  BoardDeliverableType,
  BoardHoldStatus,
  BoardMeetingMode,
  BoardStaffModelTier,
  BoardTaskOrigin,
  BoardTaskStatus,
  BoardToolGlobalMode,
  BoardToolLevel,
};

export type BoardCharterField = "vision" | "mission" | "mandate";
export const BOARD_CHARTER_FIELDS: readonly BoardCharterField[] = [
  "vision",
  "mission",
  "mandate",
];

export type BoardMember = {
  readonly id: string;
  readonly title: string;
  readonly shortName: string;
  readonly focusAreas: readonly string[];
  readonly kpisOwned: readonly string[];
  readonly vision: string;
  readonly mission: string;
  readonly mandate: string;
  readonly displayName: string;
  readonly defaults: Readonly<Record<BoardCharterField, string>>;
  readonly isOverridden: Readonly<Record<BoardCharterField | "displayName", boolean>>;
  readonly profileHash: string;
  readonly updatedAt?: string | null;
};

export type BoardMemberOverride = {
  readonly vision?: string;
  readonly mission?: string;
  readonly mandate?: string;
  readonly displayName?: string;
};

/** `{ toolId: { personaId: level } }` */
export type BoardToolMatrix = Readonly<Record<string, Readonly<Record<string, BoardToolLevel>>>>;

export type BoardSpendCaps = {
  readonly metaAdsDailyUsd: number;
  readonly metaAdsMonthlyUsd: number;
};

export type BoardAdsSpend = {
  readonly recordedDailyUsd: number;
  readonly recordedMonthlyUsd: number;
  readonly graphMonthlyUsd: number;
  readonly dailyUsd: number;
  readonly monthlyUsd: number;
  readonly dailyCapUsd: number;
  readonly monthlyCapUsd: number;
};

export type BoardToolsConfig = {
  readonly enabled: boolean;
  readonly globalMode: BoardToolGlobalMode;
  readonly matrix: BoardToolMatrix;
  /** Addresses (`name@host.tld`), domains (`@host.tld`), or E.164 phones the board may message at `act`. */
  readonly allowList: readonly string[];
  readonly spendCaps: BoardSpendCaps;
};

export type BoardSettings = {
  readonly schedule: { readonly morningEnabled: boolean; readonly eveningEnabled: boolean };
  readonly defaultMode: BoardMeetingMode;
  readonly defaultChair: string;
  readonly shareFinanceSummary: boolean;
  readonly shareRepoSnapshot: boolean;
  readonly models: { readonly chat: string; readonly standup: string; readonly deepDive: string };
  readonly dailyBudgetUsd: number;
  readonly tools: BoardToolsConfig;
  readonly staff?: {
    readonly enabled: boolean;
    readonly maxRunningTasks: number;
    readonly dailyBudgetUsd: number;
    readonly dutiesEnabled?: boolean;
    readonly seniorPaused?: boolean;
    readonly disabledReason?: string;
  };
  readonly review?: { readonly digestTo: string; readonly digestHourHkt: number; readonly sampleSize: number };
  readonly boundaries?: BoardBoundaries;
  readonly updatedAt?: string | null;
};

export type BoardBoundaries = {
  readonly reply: {
    readonly languages: readonly string[];
    readonly tone: string;
    readonly quietHoursHkt: readonly [number, number] | readonly number[];
    readonly maxOutboundPerChannelPerDay: Readonly<Record<string, number>>;
    readonly maxMessagesPerThreadPerDay: number;
    readonly sensitiveTemplatesOnly: readonly string[];
  };
  readonly escalation: {
    readonly keywords: readonly string[];
    readonly refundThresholdHkd: number;
    readonly ackTemplateId: string;
  };
  readonly holds: Readonly<Record<string, number>>;
  readonly holdOverrides: Readonly<Record<string, number>>;
  readonly outreach?: Readonly<Record<string, unknown>>;
  readonly content?: Readonly<Record<string, unknown>>;
  readonly intel?: Readonly<Record<string, unknown>>;
};

export type BoardHold = {
  readonly holdId: string;
  readonly status: BoardHoldStatus;
  readonly actionClass: BoardActionClass | string;
  readonly classKey: string;
  readonly personaId: string;
  readonly seatId?: string;
  readonly taskId?: string;
  readonly displayName?: string;
  readonly op: string;
  readonly toolId: string;
  readonly arguments: Readonly<Record<string, unknown>>;
  readonly preview?: BoardApprovalPreview;
  readonly summary: string;
  readonly createdAt: string;
  readonly executeAt: string;
  readonly executedAt?: string | null;
  readonly vetoedAt?: string | null;
  readonly vetoBy?: string;
  readonly vetoReason?: string;
  readonly result?: Readonly<Record<string, unknown>>;
};

export const DEFAULT_BOARD_BOUNDARIES: BoardBoundaries = {
  reply: {
    languages: ["en", "zh-HK"],
    tone: "Warm, plain, brief. Never promise refunds, legal positions, or availability the catalog does not show.",
    quietHoursHkt: [22, 8],
    maxOutboundPerChannelPerDay: { mail: 60, whatsapp: 60, meta: 100 },
    maxMessagesPerThreadPerDay: 3,
    sensitiveTemplatesOnly: ["payment_dispute", "cancellation", "safeguarding", "data_request"],
  },
  escalation: {
    keywords: [
      "refund",
      "lawyer",
      "legal",
      "police",
      "injury",
      "hurt",
      "abuse",
      "complaint",
      "media",
      "journalist",
      "PDPO",
      "delete my data",
      "unsubscribe me from everything",
    ],
    refundThresholdHkd: 0,
    ackTemplateId: "ack_escalation",
  },
  holds: {
    internal: 0,
    inbound_reply: 0,
    outbound_known: 0,
    cold_outreach: 24,
    publish: 24,
    spend: 24,
    code_staging: 12,
  },
  holdOverrides: {},
};

export type BoardRampState = {
  readonly classKey: string;
  readonly actions: number;
  readonly vetoes: number;
  readonly rate: number;
  readonly eligibleForPromotion: boolean;
  readonly shouldDemote: boolean;
  readonly totals?: { readonly actions: number; readonly vetoes: number };
};

export type BoardSeat = {
  readonly id: string;
  readonly reportsTo: string;
  readonly title: string;
  readonly modelTier: BoardStaffModelTier;
  readonly isActive: boolean;
  readonly isActiveDefault: boolean;
  readonly tools: Readonly<Record<string, BoardToolLevel>>;
  readonly brief: string;
  readonly displayName: string;
  readonly defaults: { readonly brief: string; readonly displayName: string; readonly modelTier: BoardStaffModelTier };
  readonly isOverridden: {
    readonly brief: boolean;
    readonly displayName: boolean;
    readonly isActive: boolean;
    readonly modelTier: boolean;
  };
  readonly effectiveLevels: Readonly<Record<string, BoardToolLevel>>;
  readonly updatedAt?: string | null;
};

export type BoardTaskUsage = {
  readonly promptTokens: number;
  readonly completionTokens: number;
  readonly cost: number;
  readonly calls: number;
};

export type BoardTask = {
  readonly taskId: string;
  readonly status: BoardTaskStatus;
  readonly assignee: string;
  readonly assigneeKind: "persona" | "seat";
  readonly managerId: string;
  readonly origin: BoardTaskOrigin;
  readonly brief: string;
  readonly deliverableType: BoardDeliverableType;
  readonly budgetUsd: number;
  readonly slaAt: string;
  readonly step: number;
  readonly stepsUsed: number;
  readonly revisions: number;
  readonly usage: BoardTaskUsage;
  readonly summary: string;
  readonly evidence: readonly string[];
  readonly openQuestions: readonly string[];
  readonly confidence: string;
  readonly flags?: readonly string[];
  readonly reviews: number;
  readonly lastReview?: { readonly verdict: string; readonly notes: string; readonly at: string; readonly by?: string } | null;
  readonly createdAt: string;
  readonly createdBy?: string;
  readonly updatedAt: string;
  readonly startedAt?: string | null;
  readonly finishedAt?: string | null;
  readonly failureReason?: string;
  readonly actionId?: string | null;
  readonly meetingId?: string | null;
  readonly eventRef?: { readonly kind?: string; readonly id?: string; readonly channel?: string; readonly subject?: string; readonly stars?: number } | null;
  readonly deliverableKey?: string;
  readonly deliverableBytes?: number;
};

export type BoardTaskStep = {
  readonly seq: number;
  readonly plan: string;
  readonly callIds: readonly string[];
  readonly usage?: Partial<BoardTaskUsage>;
  readonly at: string;
};

export type BoardTaskReview = {
  readonly seq: number;
  readonly verdict: string;
  readonly notes: string;
  readonly at: string;
  readonly by: string;
};

export type BoardStaffPayload = {
  readonly enabled: boolean;
  readonly envEnabled: boolean;
  readonly seats: readonly BoardSeat[];
  readonly counts: Readonly<Record<string, number>>;
};

export type BoardTaskListPayload = {
  readonly tasks: readonly BoardTask[];
  readonly counts: Readonly<Record<string, number>>;
};

export type BoardTaskDetailPayload = {
  readonly task: BoardTask;
  readonly steps: readonly BoardTaskStep[];
  readonly reviews: readonly BoardTaskReview[];
  readonly deliverable: string;
  readonly deliverableUrl: string;
};

export type BoardSeatOverride = {
  readonly displayName?: string;
  readonly brief?: string;
  readonly isActive?: boolean;
  readonly modelTier?: BoardStaffModelTier;
};

export type BoardTaskCreate = {
  readonly assignee: string;
  readonly brief: string;
  readonly deliverableType: BoardDeliverableType;
  readonly slaHours?: number;
  readonly budgetUsd?: number;
};

export type BoardToolOperation = {
  readonly name: string;
  readonly kind: "read" | "write";
  readonly description: string;
  readonly contexts: readonly string[];
};

export type BoardToolRegistryEntry = {
  readonly id: string;
  readonly label: string;
  readonly description: string;
  readonly maxLevel: BoardToolLevel;
  readonly operations: readonly BoardToolOperation[];
};

export type BoardToolsPayload = {
  readonly config: BoardToolsConfig;
  readonly effective: BoardToolMatrix;
  readonly enabled: boolean;
  readonly envDisabled: boolean;
  readonly registry: readonly BoardToolRegistryEntry[];
  readonly defaults: BoardToolsConfig;
  readonly repoWriteEnabled: boolean;
  readonly mailSendEnabled: boolean;
  readonly mailDomain: string;
  readonly searchConfigured?: boolean;
  readonly dataApiConfigured?: boolean;
  readonly metaConfigured?: boolean;
  readonly storesConfigured?: boolean;
  readonly webConfigured?: boolean;
  readonly adsSpend?: BoardAdsSpend;
};

export type BoardToolCallStatus = "ok" | "error" | "pending_approval" | "held";

/** One tool call as shown on a chat reply or a meeting transcript entry. */
export type BoardToolCallRef = {
  readonly callId: string;
  readonly op: string;
  readonly toolId: string;
  readonly toolLabel: string;
  readonly kind: "read" | "write";
  readonly status: BoardToolCallStatus;
  readonly summary: string;
  readonly durationMs: number;
  readonly approvalId?: string;
  readonly holdId?: string;
  readonly executeAt?: string;
  readonly error?: string;
};

/** Audit-log row (`GET /board/tools/calls`). */
export type BoardToolCallLogEntry = BoardToolCallRef & {
  readonly personaId: string;
  readonly displayName: string;
  readonly actor: "persona" | "owner";
  readonly level: BoardToolLevel;
  readonly arguments: Readonly<Record<string, unknown>>;
  readonly resultPreview: string;
  readonly context: { readonly kind: string; readonly meetingId?: string; readonly phase?: string; readonly jobId?: string };
  readonly createdAt: string;
};

export type BoardApprovalStatus = "pending" | "approved" | "executed" | "rejected" | "failed";

export type BoardApproval = {
  readonly approvalId: string;
  readonly status: BoardApprovalStatus;
  readonly personaId: string;
  readonly displayName: string;
  readonly toolId: string;
  readonly toolLabel: string;
  readonly op: string;
  readonly kind: "write";
  readonly arguments: Readonly<Record<string, unknown>>;
  readonly summary: string;
  readonly reason: string;
  readonly context: { readonly kind: string; readonly meetingId?: string; readonly phase?: string; readonly jobId?: string };
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly decidedAt?: string;
  readonly note?: string;
  readonly result?: Readonly<Record<string, unknown>>;
  readonly errorMessage?: string;
  /** Present when an `act`-level call was held back (e.g. recipient not allow-listed). */
  readonly downgradeReason?: string;
  /** Owner-facing rendering of the payload (un-masked), when the operation provides one. */
  readonly preview?: BoardApprovalPreview;
};

export type BoardMailPreview = {
  readonly kind: "email";
  readonly from: string;
  readonly to: readonly string[];
  readonly cc: readonly string[];
  readonly subject: string;
  readonly text: string;
  readonly threadId: string;
  readonly sendEnabled: boolean;
};

export type BoardPhishingPreview = {
  readonly kind: "phishing";
  readonly threadId: string;
  readonly subject: string;
  readonly mailbox: string;
  readonly from: string;
  readonly note: string;
};

export type BoardApprovalPreview = BoardMailPreview | BoardPhishingPreview | { readonly error: string };

export function isMailPreview(preview: BoardApprovalPreview | undefined): preview is BoardMailPreview {
  return !!preview && "kind" in preview && preview.kind === "email";
}

export function isPhishingPreview(preview: BoardApprovalPreview | undefined): preview is BoardPhishingPreview {
  return !!preview && "kind" in preview && preview.kind === "phishing";
}

export type ApprovalEditField = {
  readonly key: string;
  readonly label: string;
  readonly multiline: boolean;
  readonly value: string;
};

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

export type BoardMailAttachment = {
  readonly name: string;
  readonly contentType: string;
  readonly size: number;
  readonly text?: string;
};

export type BoardMailThread = {
  readonly threadId: string;
  readonly mailbox: string;
  readonly subject: string;
  readonly participants: readonly string[];
  readonly firstMessageAt: string;
  readonly lastMessageAt: string;
  readonly lastDirection: "in" | "out";
  readonly lastFrom: string;
  readonly lastFromName?: string;
  readonly messageCount: number;
  readonly unread: boolean;
  readonly hasAttachments: boolean;
  readonly snippet: string;
};

export type BoardMailMessage = {
  readonly messageId: string;
  readonly threadId: string;
  readonly direction: "in" | "out";
  readonly source: string;
  readonly mailbox: string;
  readonly from: { readonly address: string; readonly name: string };
  readonly to: readonly string[];
  readonly cc: readonly string[];
  readonly subject: string;
  readonly date: string;
  readonly receivedAt: string;
  readonly text: string;
  readonly attachments: readonly BoardMailAttachment[];
};

/** Masked rendering (`?view=board`): what a persona sees through the mail tools. */
export type BoardMailMaskedMessage = {
  readonly messageId: string;
  readonly direction: "in" | "out";
  readonly from: string;
  readonly to: readonly string[];
  readonly cc: readonly string[];
  readonly date: string;
  readonly subject: string;
  readonly text: string;
  readonly attachments: readonly BoardMailAttachment[];
};

export type BoardMailboxSummary = {
  readonly address: string;
  readonly threadCount: number;
  readonly unreadCount: number;
  readonly lastMessageAt: string;
};

export type BoardMailStatus = {
  readonly threadCount: number;
  readonly unreadCount: number;
  readonly domain: string;
  readonly sendEnabled: boolean;
  readonly inboundAddress: string;
};

export type BoardMailListPayload = {
  readonly threads: readonly BoardMailThread[];
  readonly total: number;
  readonly mailboxes: readonly BoardMailboxSummary[];
  readonly status: BoardMailStatus;
};

export type BoardMailThreadPayload = {
  readonly thread: BoardMailThread;
  readonly messages: readonly BoardMailMessage[];
};

export type BoardCharter = {
  readonly vision: string;
  readonly mission: string;
  readonly updatedAt?: string | null;
};

export type BoardBrief = {
  readonly markdown: string;
  readonly updatedAt?: string | null;
};

export type BoardUsage = {
  readonly promptTokens: number;
  readonly completionTokens: number;
  readonly totalTokens: number;
  readonly cost: number;
  readonly calls?: number;
};

/** Non-OpenRouter usage counters for the current day; absent on stacks that predate them. */
export type BoardExternalUsageToday = {
  readonly searchCalls: number;
  readonly metaAdsMonthUsd: number;
};

export type BoardUsageToday = BoardUsage & {
  readonly budgetUsd: number;
  readonly external?: BoardExternalUsageToday;
};

export type BoardMeetingStatus = "running" | "succeeded" | "failed" | "cancelled";

export type BoardMeetingSummary = {
  readonly meetingId: string;
  readonly status: BoardMeetingStatus;
  readonly mode: BoardMeetingMode;
  readonly chair: string;
  readonly topic: string;
  readonly trigger: string;
  readonly phase: string;
  readonly phases: readonly string[];
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly headline: string;
  readonly actionCount: number;
  readonly usage: BoardUsage;
  readonly errorMessage?: string | null;
};

export type BoardAgendaItem = {
  readonly title: string;
  readonly question: string;
  readonly whyNow?: string;
};

export type BoardMinutesAction = {
  readonly title: string;
  readonly detail: string;
  readonly persona: string;
  readonly priority: BoardActionPriority;
  readonly effort: string;
  readonly dueInDays: number | null;
  readonly metric: string;
  readonly dependsOn?: readonly string[];
  readonly existingActionId?: string;
};

export type BoardMinutes = {
  readonly headline: string;
  readonly agenda: readonly { readonly title: string; readonly question: string }[];
  readonly discussion: readonly {
    readonly agendaIndex: number;
    readonly summary: string;
    readonly consensus: "agree" | "split" | "deferred";
  }[];
  readonly decisions: readonly { readonly text: string; readonly proposedBy: string; readonly rationale: string }[];
  readonly risks: readonly { readonly text: string; readonly owner: string; readonly severity: "high" | "medium" | "low" }[];
  readonly actions: readonly BoardMinutesAction[];
  readonly questionsForOwner: readonly string[];
};

export type BoardMeetingDetail = BoardMeetingSummary & {
  readonly agenda: readonly BoardAgendaItem[];
  readonly conflicts: readonly {
    readonly topic: string;
    readonly summary: string;
    readonly askedOf: readonly string[];
    readonly question: string;
  }[];
  readonly minutes: BoardMinutes | null;
  readonly roster: readonly { readonly id: string; readonly displayName: string; readonly title: string }[];
  readonly contextPackHash?: string;
  readonly contextPackChars?: number;
  readonly memberProfileHashes: Readonly<Record<string, string>>;
  readonly models: Readonly<Record<string, string>>;
  readonly createdActionIds: readonly string[];
  readonly reaffirmedActionIds: readonly string[];
  readonly turnCount: number;
};

export type BoardTurn = {
  readonly seq: number;
  readonly phase: string;
  readonly personaId: string;
  readonly displayName: string;
  readonly title: string;
  readonly text: string;
  readonly usage?: BoardUsage;
  readonly model?: string;
  readonly createdAt: string;
  /** `"tool"` turns list what a member looked up or proposed before speaking. */
  readonly kind?: "tool";
  readonly data?: { readonly calls?: readonly BoardToolCallRef[] };
};

export type BoardAction = {
  readonly actionId: string;
  readonly title: string;
  readonly detail: string;
  readonly persona: string;
  readonly priority: BoardActionPriority;
  readonly effort: string;
  readonly metric: string;
  readonly dependsOn: readonly string[];
  readonly status: BoardActionStatus;
  readonly note: string;
  readonly meetingId: string;
  readonly reaffirmedByMeetingIds: readonly string[];
  readonly dueAt: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
};

export type BoardChatMessage = {
  readonly messageId: string;
  readonly role: "user" | "assistant";
  readonly text: string;
  readonly createdAt: string;
  readonly usage?: BoardUsage;
  readonly model?: string;
  readonly suggestedMeeting?: { readonly mode: BoardMeetingMode; readonly topic: string };
  readonly toolCalls?: readonly BoardToolCallRef[];
  /** Client-only: reply still being generated. */
  readonly isPending?: boolean;
};

export type BoardUpdate = {
  readonly updateId: string;
  readonly text: string;
  readonly createdAt: string;
};

export type BoardRepoSnapshotMeta = {
  readonly repo: string;
  readonly fetchedAt: string;
  readonly openIssuesCount: number;
  readonly docs: readonly string[];
  readonly commits: number;
  readonly ci: { readonly name: string; readonly status: string; readonly conclusion: string | null } | null;
  readonly chars: number;
};

export type BoardOverview = {
  readonly settings: BoardSettings;
  readonly charter: BoardCharter;
  readonly brief: BoardBrief;
  readonly members: readonly BoardMember[];
  readonly chairDefault: string;
  readonly openActionCount: number;
  readonly runningMeeting: BoardMeetingSummary | null;
  readonly latestMeeting: BoardMeetingSummary | null;
  readonly usageToday: BoardUsageToday;
  readonly models: { readonly chat: string; readonly standup: string; readonly deepDive: string };
  readonly repoSnapshot: BoardRepoSnapshotMeta | null;
  readonly repoSnapshotEnabled: boolean;
  readonly repoWriteEnabled: boolean;
  readonly repo: string;
  readonly pendingApprovalCount: number;
  readonly toolsEnabled: boolean;
  readonly unreadMailCount: number;
  readonly overdueInvoiceCount?: number;
  readonly mail: BoardMailStatus;
  readonly receivables?: { readonly outstandingHkd?: number; readonly overdue?: number };
};

export type BoardReceivablesInvoice = {
  readonly id: string;
  readonly number: string;
  readonly amount_hkd: number;
  readonly status: string;
  readonly due_on?: string | null;
  readonly fps_reference?: string | null;
  readonly subscription_id?: string | null;
};

export type BoardReceivablesSubscription = {
  readonly id: string;
  readonly organization_id: string;
  readonly status: string;
  readonly plan_name?: string | null;
  readonly price_hkd?: number | null;
  readonly renews_on?: string | null;
  readonly payer_contact?: string | null;
};

export type BoardReceivablesAging = {
  readonly asOf?: string;
  readonly outstandingHkd: number;
  readonly dso?: number;
  readonly buckets: Readonly<Record<string, readonly BoardReceivablesInvoice[]>>;
};

export type BoardReceivablesPayload = {
  readonly configured: boolean;
  readonly invoices: readonly BoardReceivablesInvoice[];
  readonly subscriptions: readonly BoardReceivablesSubscription[];
  readonly aging: BoardReceivablesAging;
};

export const BOARD_API_BASE = "/siu-tin-dei/board";

export const TOOL_LEVEL_LABELS: Readonly<Record<BoardToolLevel, string>> = {
  off: "Off",
  read: "Read",
  propose: "Propose",
  act: "Act",
};

export const TOOL_LEVEL_HELP: Readonly<Record<BoardToolLevel, string>> = {
  off: "No access to this tool.",
  read: "Look things up; never change anything.",
  propose: "Read, and queue writes for your approval.",
  act: "Read and write directly (logged).",
};

export const TOOL_GLOBAL_MODE_LABELS: Readonly<Record<BoardToolGlobalMode, string>> = {
  readOnly: "Read-only",
  propose: "Propose (writes need approval)",
  act: "Act (per-member levels apply)",
};

export const TOOL_LEVEL_BADGE_CLASS: Readonly<Record<BoardToolLevel, string>> = {
  off: "text-bg-light border text-muted",
  read: "text-bg-secondary",
  propose: "text-bg-warning",
  act: "text-bg-success",
};

export const TOOL_CALL_STATUS_ICON: Readonly<Record<BoardToolCallStatus, { readonly icon: string; readonly className: string; readonly label: string }>> = {
  ok: { icon: "bi-check-circle-fill", className: "text-success", label: "done" },
  error: { icon: "bi-x-circle-fill", className: "text-danger", label: "failed" },
  pending_approval: { icon: "bi-hourglass-split", className: "text-warning", label: "awaiting approval" },
  held: { icon: "bi-clock-history", className: "text-info", label: "scheduled" },
};

export const APPROVAL_STATUS_BADGE_CLASS: Readonly<Record<BoardApprovalStatus, string>> = {
  pending: "text-bg-warning",
  approved: "text-bg-info",
  executed: "text-bg-success",
  rejected: "text-bg-secondary",
  failed: "text-bg-danger",
};

/** Levels above the tool's own ceiling (e.g. read-only connectors) are not offered. */
export function levelsUpTo(maxLevel: BoardToolLevel): readonly BoardToolLevel[] {
  const idx = BOARD_TOOL_LEVELS.indexOf(maxLevel);
  return BOARD_TOOL_LEVELS.slice(0, idx + 1);
}

/** Mirrors `board_tools.effective_level`: the global mode caps every configured level. */
export function effectiveToolLevel(config: BoardToolsConfig, toolId: string, personaId: string): BoardToolLevel {
  if (!config.enabled) return "off";
  const configured = config.matrix[toolId]?.[personaId] ?? "off";
  const cap: BoardToolLevel = config.globalMode === "readOnly" ? "read" : config.globalMode === "propose" ? "propose" : "act";
  return BOARD_TOOL_LEVELS.indexOf(configured) <= BOARD_TOOL_LEVELS.indexOf(cap) ? configured : cap;
}

export function defaultToolMatrix(): BoardToolMatrix {
  const out: Record<string, Record<string, BoardToolLevel>> = {};
  for (const tool of BOARD_TOOL_DEFINITIONS) out[tool.id] = { ...tool.defaults };
  return out;
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

/** Merge contract defaults with an owner override into the effective profile (mirrors the Lambda). */
export function mergeMemberProfile(
  base: Pick<BoardMember, "id" | "title" | "shortName" | "focusAreas" | "kpisOwned"> &
    Readonly<Record<BoardCharterField, string>>,
  override: BoardMemberOverride | null | undefined,
): Omit<BoardMember, "profileHash"> {
  const ov = override ?? {};
  const isOverridden = {
    vision: Boolean(ov.vision?.trim()),
    mission: Boolean(ov.mission?.trim()),
    mandate: Boolean(ov.mandate?.trim()),
    displayName: Boolean(ov.displayName?.trim()),
  };
  return {
    id: base.id,
    title: base.title,
    shortName: base.shortName,
    focusAreas: base.focusAreas,
    kpisOwned: base.kpisOwned,
    defaults: { vision: base.vision, mission: base.mission, mandate: base.mandate },
    vision: isOverridden.vision ? ov.vision!.trim() : base.vision,
    mission: isOverridden.mission ? ov.mission!.trim() : base.mission,
    mandate: isOverridden.mandate ? ov.mandate!.trim() : base.mandate,
    displayName: isOverridden.displayName ? ov.displayName!.trim() : base.shortName,
    isOverridden,
  };
}

export function defaultMemberProfiles(): readonly Omit<BoardMember, "profileHash">[] {
  return BOARD_PERSONA_DEFAULTS.map((p) => mergeMemberProfile(p, null));
}

export function memberInitials(member: Pick<BoardMember, "displayName" | "shortName">): string {
  const name = member.displayName.trim();
  if (!name) return member.shortName.slice(0, 3).toUpperCase();
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 3).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function memberLabel(
  members: readonly Pick<BoardMember, "id" | "displayName" | "shortName">[],
  personaId: string,
): string {
  const found = members.find((m) => m.id === personaId);
  if (!found) return personaId ? personaId.toUpperCase() : "Board";
  return found.displayName === found.shortName
    ? found.shortName
    : `${found.displayName} (${found.shortName})`;
}

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

export function boardMemberPath(personaId: string): string {
  return `${BOARD_API_BASE}/members/${encodeURIComponent(personaId)}`;
}

export function boardChatPath(personaId: string): string {
  return `${BOARD_API_BASE}/chat/${encodeURIComponent(personaId)}`;
}

export function boardChatJobPath(personaId: string, jobId: string): string {
  return `${boardChatPath(personaId)}/jobs/${encodeURIComponent(jobId)}`;
}

export function boardMeetingPath(meetingId: string): string {
  return `${BOARD_API_BASE}/meetings/${encodeURIComponent(meetingId)}`;
}

export function boardActionPath(actionId: string): string {
  return `${BOARD_API_BASE}/actions/${encodeURIComponent(actionId)}`;
}

export function boardApprovalDecisionPath(approvalId: string, decision: "approve" | "reject"): string {
  return `${BOARD_API_BASE}/approvals/${encodeURIComponent(approvalId)}/${decision}`;
}

export function boardMailThreadPath(threadId: string): string {
  return `${BOARD_API_BASE}/mail/${encodeURIComponent(threadId)}`;
}

export function boardStaffPath(seatId?: string): string {
  return seatId ? `${BOARD_API_BASE}/staff/${encodeURIComponent(seatId)}` : `${BOARD_API_BASE}/staff`;
}

export function boardTasksPath(query?: { status?: string; assignee?: string; limit?: number }): string {
  const params = new URLSearchParams();
  if (query?.status) params.set("status", query.status);
  if (query?.assignee) params.set("assignee", query.assignee);
  if (query?.limit) params.set("limit", String(query.limit));
  const qs = params.toString();
  return qs ? `${BOARD_API_BASE}/tasks?${qs}` : `${BOARD_API_BASE}/tasks`;
}

export function boardTaskPath(taskId: string): string {
  return `${BOARD_API_BASE}/tasks/${encodeURIComponent(taskId)}`;
}

export function boardTaskCancelPath(taskId: string): string {
  return `${boardTaskPath(taskId)}/cancel`;
}

export function boardTaskReviewPath(taskId: string): string {
  return `${boardTaskPath(taskId)}/review`;
}

export function boardHoldsPath(query?: { status?: string; limit?: number }): string {
  const params = new URLSearchParams();
  if (query?.status) params.set("status", query.status);
  if (query?.limit) params.set("limit", String(query.limit));
  const qs = params.toString();
  return qs ? `${BOARD_API_BASE}/holds?${qs}` : `${BOARD_API_BASE}/holds`;
}

export function boardHoldVetoPath(holdId: string): string {
  return `${BOARD_API_BASE}/holds/${encodeURIComponent(holdId)}/veto`;
}

export function boardHoldVetoClassPath(): string {
  return `${BOARD_API_BASE}/holds/veto-class`;
}

export function boardBoundariesPath(): string {
  return `${BOARD_API_BASE}/boundaries`;
}

export function boardRampPath(): string {
  return `${BOARD_API_BASE}/ramp`;
}

export function boardRampPromotePath(classKey: string): string {
  return `${BOARD_API_BASE}/ramp/${encodeURIComponent(classKey)}/promote`;
}

export function boardReviewPath(date?: string): string {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  const qs = params.toString();
  return qs ? `${BOARD_API_BASE}/review?${qs}` : `${BOARD_API_BASE}/review`;
}

export function boardReviewWrongPath(callId: string): string {
  return `${BOARD_API_BASE}/review/sample/${encodeURIComponent(callId)}/wrong`;
}

export function boardLessonsPath(): string {
  return `${BOARD_API_BASE}/lessons`;
}

export function boardLessonConfirmPath(lessonId: string): string {
  return `${BOARD_API_BASE}/lessons/${encodeURIComponent(lessonId)}/confirm`;
}

export function boardLessonDismissPath(lessonId: string): string {
  return `${BOARD_API_BASE}/lessons/${encodeURIComponent(lessonId)}/dismiss`;
}

export function boardBreakersPath(): string {
  return `${BOARD_API_BASE}/breakers`;
}

export function boardBreakerResetPath(name: string): string {
  return `${BOARD_API_BASE}/breakers/${encodeURIComponent(name)}/reset`;
}

export type BoardRampRow = {
  readonly classKey: string;
  readonly actions: number;
  readonly vetoes: number;
  readonly rate: number;
  readonly eligibleForPromotion: boolean;
  readonly shouldDemote: boolean;
};

export type BoardBreaker = {
  readonly name: string;
  readonly tripped?: boolean;
  readonly reason?: string;
  readonly trippedAt?: string;
  readonly resetBy?: string;
  readonly resetAt?: string | null;
};

export type BoardLesson = {
  readonly lessonId: string;
  readonly subject?: string;
  readonly classKey?: string;
  readonly what?: string;
  readonly instruction: string;
  readonly confirmed?: boolean;
  readonly dismissed?: boolean;
  readonly kind?: string;
  readonly createdAt?: string;
};

export type BoardReviewSnapshot = {
  readonly date: string;
  readonly compiledAt?: string;
  readonly narrative?: string;
  readonly digestHtml?: string;
  readonly headline: {
    readonly tasks: { readonly delivered: number; readonly running: number; readonly blocked: number };
    readonly messagesByChannel: Readonly<Record<string, number>>;
    readonly holds: { readonly executed: number; readonly vetoed: number };
    readonly spend: { readonly boardUsd: number; readonly staffUsd: number; readonly budgetUsd: number };
    readonly pipeline?: Readonly<Record<string, unknown>>;
    readonly content?: Readonly<Record<string, unknown>>;
    readonly market?: Readonly<Record<string, unknown>>;
  };
  readonly holdsDue: readonly BoardHold[];
  readonly escalations: readonly {
    readonly taskId: string;
    readonly assignee?: string;
    readonly brief?: string;
    readonly suggestedReply?: { readonly summary?: string; readonly preview?: unknown } | null;
  }[];
  readonly sample: readonly {
    readonly callId: string;
    readonly summary?: string;
    readonly preview?: unknown;
    readonly op?: string;
  }[];
  readonly breakers: readonly BoardBreaker[];
  readonly suggestions: readonly BoardRampRow[];
  readonly assisted?: readonly unknown[];
  readonly market?: readonly unknown[];
  readonly promotion?: readonly unknown[];
};

export function tasksNeedPolling(tasks: readonly BoardTask[]): boolean {
  return tasks.some((t) => t.status === "running" || t.status === "review");
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
