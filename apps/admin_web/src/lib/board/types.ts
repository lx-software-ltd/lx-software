import {
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
} from "../contracts/generated";

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
    readonly modelBySeat?: Readonly<Record<string, string>>;
  };
  readonly review?: { readonly digestTo: string; readonly digestHourHkt: number; readonly sampleSize: number };
  readonly catalog?: {
    readonly autoImport?: boolean;
    readonly microBatchEnabled?: boolean;
    readonly launchListingTarget?: number;
  };
  readonly dmarc?: BoardDmarcSettings;
  readonly boundaries?: BoardBoundaries;
  readonly updatedAt?: string | null;
  readonly version?: number;
};


export type BoardDmarcSettings = {
  readonly enabled?: boolean;
  readonly knownSenderDomains?: readonly string[];
  readonly spoofAlertCount?: number;
  readonly silenceDays?: number;
  readonly expectedPolicy?: {
    readonly p?: string;
    readonly pct?: number;
    readonly sp?: string;
  };
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
    code_production: 0,
    catalog_import: 2,
  },
  holdOverrides: {},
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
  readonly parentTaskId?: string | null;
  readonly helpTaskIds?: readonly string[];
  readonly blockedOn?: readonly string[];
  readonly parkedAt?: string;
  readonly parkedReason?: string;
  readonly eventRef?: {
    readonly kind?: string;
    readonly id?: string;
    readonly channel?: string;
    readonly subject?: string;
    readonly stars?: number;
    readonly prNumber?: number;
    readonly issueNumber?: number;
    readonly districtId?: string;
    readonly district?: string;
  } | null;
  readonly deliverableKey?: string;
  readonly deliverableBytes?: number;
  readonly importedAt?: string;
  readonly acceptedAt?: string;
  readonly importPhase?: string;
  readonly importError?: string;
  readonly importAttempts?: number;
  readonly revalidateAttempts?: number;
  readonly lastImportAttemptAt?: string;
  readonly importSkipped?: boolean;
  readonly importPreview?: BoardCatalogImportPreview | null;
  readonly importResult?: BoardCatalogImportResult | null;
};


export type BoardCatalogImportPreview = {
  readonly ok: boolean;
  readonly taskId?: string;
  readonly district?: string;
  readonly importEnabled?: boolean;
  readonly configured?: boolean;
  readonly error?: string;
  readonly dryRun?: {
    readonly ok?: boolean;
    readonly mode?: string;
    readonly accepted?: number;
    readonly skipped?: number;
    readonly errors?: readonly string[];
    readonly remoteError?: string;
    readonly wouldUpdate?: readonly string[];
    readonly summary?: {
      readonly created?: number;
      readonly updated?: number;
      readonly failed?: number;
      readonly skipped?: number;
    };
    readonly results?: readonly {
      readonly type?: string;
      readonly key?: string;
      readonly status?: string;
      readonly errors?: readonly { readonly message?: string }[];
    }[];
  };
  readonly payload?: { readonly organizations?: readonly Record<string, unknown>[] };
};


export type BoardCatalogImportResult = {
  readonly ok?: boolean;
  readonly sent?: number;
  readonly accepted?: number;
  readonly created?: number;
  readonly updated?: number;
  readonly failed?: number;
  readonly failedActivities?: number;
  readonly objectKey?: string;
  readonly at?: string;
  readonly partial?: boolean;
  readonly summary?: {
    readonly created?: number;
    readonly updated?: number;
    readonly failed?: number;
    readonly skipped?: number;
  };
  readonly results?: readonly {
    readonly type?: string;
    readonly key?: string;
    readonly status?: string;
    readonly errors?: readonly { readonly message?: string }[];
  }[];
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
  /** Founder action this task works on; accepted deliverables close it. */
  readonly actionId?: string;
  /** Existing board PR to revise (sets eventRef.prNumber). */
  readonly prNumber?: number;
  /** Linked GitHub issue when the PR row has none. */
  readonly issueNumber?: number;
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


export type ApprovalEditField = {
  readonly key: string;
  readonly label: string;
  readonly multiline: boolean;
  readonly value: string;
};


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
  readonly disposition?: string;
  readonly archivedReason?: string;
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


/** What SES itself says about our ability to send (mail list only; cached 10 min server-side). */
export type BoardMailSendHealth = {
  readonly checkedAt: string;
  readonly identityVerified: boolean | null;
  readonly dkimStatus: string | null;
  readonly productionAccess: boolean | null;
  readonly dailyQuota?: number;
  readonly sentLast24h?: number;
  readonly errors: readonly string[];
};


export type BoardMailStatus = {
  readonly threadCount: number;
  readonly unreadCount: number;
  readonly domain: string;
  readonly sendEnabled: boolean;
  readonly inboundAddress: string;
  readonly sendHealth?: BoardMailSendHealth;
};


export type BoardMailSelfTestResult = {
  readonly ok: true;
  readonly to: string;
  readonly from: string;
  readonly sesMessageId: string;
  readonly health: BoardMailSendHealth;
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
  /** Seat or persona working this action; empty means the founder. */
  readonly assignee?: string;
  /** Staff task currently (or last) working this action. */
  readonly staffTaskId?: string;
  readonly closedBy?: string;
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


export type BoardOutreachIdentity = {
  readonly domain: string;
  readonly fromAddress?: string;
  readonly identityVerified: boolean | null;
  readonly dkimStatus: string | null;
  readonly dkimRecords: readonly { readonly name: string; readonly value: string }[];
  readonly mailFromDomain: string | null;
  readonly mailFromStatus: string | null;
  readonly errors: readonly string[];
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
  readonly outreachIdentity?: BoardOutreachIdentity;
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


export type BoardCatalogCandidateQuery = {
  readonly status?: string;
  readonly source?: string;
  readonly district?: string;
  readonly q?: string;
  readonly missingPlaceId?: boolean;
  readonly limit?: number;
  readonly cursor?: number;
};


export type BoardStagingPreview = {
  readonly status?: string;
  readonly behindBy?: number;
  readonly aheadBy?: number;
  readonly canPromote?: boolean;
  readonly syncOnly?: boolean;
  readonly htmlUrl?: string;
  readonly error?: string;
  readonly commits?: readonly { readonly sha?: string; readonly message?: string }[];
};


export type BoardStagingSyncResult = {
  readonly ok?: boolean;
  readonly alreadyCurrent?: boolean;
  readonly reset?: boolean;
  readonly fastForward?: boolean;
  readonly mergedSha?: string;
  readonly before?: BoardStagingPreview;
  readonly preview?: BoardStagingPreview;
  readonly error?: string;
};


export type BoardContentItem = {
  readonly contentId: string;
  readonly status?: string;
  readonly channel?: string;
  readonly pillar?: string;
  readonly slotAt?: string;
  readonly copyEn?: string;
  readonly copyZh?: string;
  readonly hashtags?: readonly string[];
  readonly template?: string;
  readonly holdId?: string;
  readonly platformPostId?: string;
  readonly creativeKeys?: readonly string[];
  readonly performance?: Readonly<Record<string, unknown>>;
};


export type BoardProspectTouch = {
  readonly stepIndex?: number;
  readonly sentAt?: string;
  readonly subject?: string;
  readonly preview?: string;
  readonly threadId?: string;
};


export type BoardProspect = {
  readonly prospectId: string;
  readonly name: string;
  readonly type?: string;
  readonly district?: string;
  readonly stage?: string;
  readonly source?: string;
  readonly website?: string;
  readonly phone?: string;
  readonly email?: string;
  readonly contact?: string | null;
  readonly placeId?: string;
  readonly score?: number;
  readonly fitNote?: string;
  readonly ownerNote?: string;
  readonly touches?: readonly BoardProspectTouch[];
  readonly nextTouchAt?: string;
  readonly lastThreadId?: string;
  readonly qualifiedAt?: string;
  readonly createdAt?: string;
  readonly updatedAt?: string;
  readonly possibleDuplicates?: readonly { readonly prospectId: string; readonly name?: string; readonly stage?: string }[];
};


export type BoardProspectWrite = {
  readonly stage?: string;
  readonly contact?: string;
  readonly type?: string;
  readonly note?: string;
};


export type BoardSequenceStep = {
  readonly dayOffset: number;
  readonly subjectEn: string;
  readonly subjectZh: string;
  readonly bodyEn: string;
  readonly bodyZh: string;
};


export type BoardSequence = {
  readonly type: string;
  readonly steps: readonly BoardSequenceStep[];
};


export type BoardOutreachStats = {
  readonly sent?: number;
  readonly bounces?: number;
  readonly complaints?: number;
  readonly bounceRate?: number;
  readonly complaintRate?: number;
  readonly replies?: number;
  readonly dailyCap?: number;
  readonly capRaisedAt?: string;
  readonly identityVerified?: boolean;
  readonly identity?: BoardOutreachIdentity;
  readonly breaker?: { readonly name?: string; readonly tripped?: boolean; readonly reason?: string };
  readonly history?: readonly { readonly date: string; readonly sent?: number; readonly bounces?: number; readonly complaints?: number }[];
};


export type BoardWatchPage = {
  readonly url?: string;
  readonly emptyBody?: boolean;
  readonly lastFetchedAt?: string;
  readonly status?: number;
};


export type BoardWatch = {
  readonly watchId: string;
  readonly name: string;
  readonly kind: string;
  readonly urls: readonly string[];
  readonly district?: string;
  readonly appIds?: Readonly<Record<string, string>>;
  readonly socialHandles?: readonly string[];
  readonly seenWeeks?: readonly string[];
  readonly createdAt?: string;
  readonly updatedAt?: string;
  readonly pages?: readonly BoardWatchPage[];
};


export type BoardWatchWrite = {
  readonly name?: string;
  readonly kind?: string;
  readonly urls?: readonly string[];
  readonly district?: string;
  readonly appIds?: Readonly<Record<string, string>>;
  readonly socialHandles?: readonly string[];
};


export type BoardChangeNote = {
  readonly changeId: string;
  readonly watchId?: string;
  readonly url?: string;
  readonly kind?: string;
  readonly summary?: string;
  readonly createdAt?: string;
  readonly beforeDigest?: string;
  readonly afterDigest?: string;
  readonly beforeKey?: string;
  readonly afterKey?: string;
};


export type BoardMarketBrief = {
  readonly taskId: string;
  readonly status?: string;
  readonly summary?: string;
  readonly createdAt?: string;
  readonly eventRef?: { readonly kind?: string; readonly id?: string };
};


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


export type BoardProgressGap = {
  readonly kind?: string;
  readonly label: string;
  readonly detail: string;
};


export type BoardProgressStalledSigning = {
  readonly id: string;
  readonly name: string;
  readonly step: string;
  readonly status: string;
  readonly daysSinceLastEdit: number;
  readonly signedUpOn?: string;
};


export type BoardProgressStalledProspect = {
  readonly id: string;
  readonly name: string;
  readonly stage: string;
  readonly district?: string;
  readonly nextTouchAt?: string;
};


export type BoardProgressBottleneck = {
  readonly id: string;
  readonly area: "listings" | "signings" | "partnerships" | "content" | string;
  readonly severity: "warning" | "danger" | string;
  readonly summary: string;
  readonly section: string;
};


export type BoardProgressSnapshot = {
  readonly fetchedAt: string;
  readonly listings: {
    readonly activities: number;
    readonly launchTarget?: number;
    readonly providers: number;
    readonly stores: number;
    readonly completenessAvg: number | null;
    readonly hasPhotoAvg?: number | null;
    readonly hasPriceAvg?: number | null;
    readonly hasScheduleAvg?: number | null;
    readonly hasGeoAvg?: number | null;
    readonly byDistrict: readonly {
      readonly label: string;
      readonly activities: number;
      readonly providers: number;
      readonly stores: number;
      readonly completenessAvg: number | null;
      readonly hasPhotoAvg?: number | null;
      readonly hasPriceAvg?: number | null;
      readonly hasScheduleAvg?: number | null;
      readonly hasGeoAvg?: number | null;
    }[];
    readonly funnel7d: { readonly listingViews: number; readonly leads: number; readonly bookings: number };
    readonly gaps: readonly BoardProgressGap[];
    readonly error?: string;
  };
  readonly signings: {
    readonly count: number;
    readonly byOnboardingStep: Readonly<Record<string, number>>;
    readonly bySubscription: Readonly<Record<string, number>>;
    readonly stalled: readonly BoardProgressStalledSigning[];
    readonly error?: string;
  };
  readonly partnerships: {
    readonly byStage: Readonly<Record<string, number>>;
    readonly qualifiedThisWeek: number;
    readonly weeklyTarget: number;
    readonly needsContact: number;
    readonly stalled: readonly BoardProgressStalledProspect[];
  };
  readonly content: {
    readonly byStatus: Readonly<Record<string, number>>;
    readonly scheduledNext7: number;
    readonly emptyChannels: readonly string[];
    readonly stalledDrafts: readonly { readonly id: string; readonly channel: string; readonly status: string; readonly slotAt: string; readonly title: string }[];
    readonly horizonDays: number;
  };
  readonly bottlenecks: readonly BoardProgressBottleneck[];
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
    readonly listings?: Readonly<Record<string, unknown>>;
    readonly signings?: Readonly<Record<string, unknown>>;
    readonly market?: Readonly<Record<string, unknown>>;
    readonly mail?: { readonly replied: number; readonly archived: number; readonly open: number };
    readonly catalog?: {
      readonly ready?: number;
      readonly importedDistricts?: number;
      readonly completeDistricts?: number;
      readonly nextDistrict?: string;
      readonly failedActivityRows?: number;
      readonly revalidateExhausted?: number;
    };
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
  readonly assisted?: readonly BoardContentItem[];
  readonly market?: {
    readonly changes?: readonly BoardChangeNote[];
    readonly latestBrief?: BoardMarketBrief | null;
  };
  readonly promotion?: BoardStagingPreview | readonly unknown[];
  readonly configGaps?: readonly {
    readonly gapId?: string;
    readonly week?: string;
    readonly reason?: string;
    readonly at?: string;
  }[];
  readonly dmarc?: {
    readonly line?: string;
    readonly findings?: readonly {
      readonly fingerprint?: string;
      readonly severity?: string;
      readonly summary?: string;
    }[];
  };
  readonly engineering?: readonly {
    readonly taskId?: string;
    readonly prNumber?: number;
    readonly ciState?: string;
    readonly ciFixRounds?: number;
    readonly ciFixMax?: number;
    readonly reviewRounds?: number;
    readonly reviewMax?: number;
    readonly failureLine?: string;
    readonly canRevise?: boolean | null;
  }[];
};


export type BoardCatalogJob = {
  readonly phase?: string;
  readonly action?: string;
  readonly at?: string;
  readonly error?: string;
  readonly ok?: boolean;
  readonly imported?: number;
  readonly approved?: number;
  readonly offset?: number;
  readonly remaining?: number;
  readonly fetched?: number;
  readonly upserted?: number;
  readonly processed?: number;
};


export type BoardCatalogSourceRow = {
  readonly id: string;
  readonly counts: Readonly<Record<string, number>>;
  readonly available: number;
  readonly lastImport?: { readonly at?: string; readonly imported?: number } | null;
  readonly lastPreview?: { readonly at?: string; readonly count?: number } | null;
  readonly job?: BoardCatalogJob | null;
};


export type BoardCatalogSourcesPayload = {
  readonly sources: readonly BoardCatalogSourceRow[];
  readonly launchTarget: number;
  readonly candidateCounts: Readonly<Record<string, Readonly<Record<string, number>>>>;
};


export type BoardCatalogCandidate = {
  readonly candidateId: string;
  readonly source: string;
  readonly nameEn: string;
  readonly nameZh?: string;
  readonly district: string;
  readonly status: string;
  readonly officialUrl?: string;
  readonly updatedAt?: string;
};
