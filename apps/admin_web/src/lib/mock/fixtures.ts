/**
 * Deterministic fixture data for `VITE_ADMIN_MOCK=1` (see mockAdminApi.ts).
 * Values are invented; they exist so every table, badge and total row renders
 * with realistic density for layout work, screenshots and Playwright checks.
 */
import type { AdminAssetMeta } from "../../hooks/useAdminAssets";
import type { BankSyncState } from "../bankSyncModel";
import {
  BOARD_PERSONA_DEFAULTS,
  BOARD_TOOL_DEFINITIONS,
} from "../contracts/generated";
import type {
  BoardAction,
  BoardApproval,
  BoardMeetingSummary,
  BoardOverview,
  BoardReceivablesPayload,
  BoardToolsConfig,
  BoardToolsPayload,
} from "../boardModel";
import type { OpenRouterUsagePayload } from "../openrouterUsage";
import type { AwsBillingPayload } from "../awsBilling";
import type { FinancePersistedState, HouseFinanceData } from "../financeModel";

const TODAY = new Date();
const isoDaysAgo = (days: number): string =>
  new Date(TODAY.getTime() - days * 86_400_000).toISOString();
const dateDaysAgo = (days: number): string => isoDaysAgo(days).slice(0, 10);

const hillmarton: HouseFinanceData = {
  defaultCurrency: "GBP",
  float: { amount: 1250, currency: "GBP" },
  lines: [
    {
      id: "hl-1",
      dateUtc: isoDaysAgo(3),
      type: "income",
      description: "Rent — September",
      netAmount: 2100,
      vat: 0,
      currency: "GBP",
      grossAmount: 2100,
    },
    {
      id: "hl-2",
      dateUtc: isoDaysAgo(9),
      type: "expenditure",
      description: "Boiler service and gas safety certificate (annual)",
      netAmount: 145,
      vat: 29,
      currency: "GBP",
      grossAmount: 174,
      sourceAssetKeys: ["uploads/hillmarton/2026-08-boiler-service.pdf"],
    },
    {
      id: "hl-3",
      dateUtc: isoDaysAgo(31),
      type: "mortgage",
      description: "Mortgage instalment",
      netAmount: 1380.42,
      vat: 0,
      currency: "GBP",
      grossAmount: 1380.42,
    },
  ],
};

const morrison: HouseFinanceData = {
  defaultCurrency: "HKD",
  float: { amount: 8000, currency: "HKD" },
  lines: [
    {
      id: "mo-1",
      dateUtc: isoDaysAgo(5),
      type: "expenditure",
      description: "Management fee",
      netAmount: 2650,
      vat: 0,
      currency: "HKD",
      grossAmount: 2650,
    },
  ],
};

export const financeFixture: FinancePersistedState = {
  hillmarton,
  morrison,
  incomeRecords: [
    { id: "in-1", category: "Salary", description: "LX Software salary", amount: 62000, currency: "HKD", amountPeriod: "month" },
    { id: "in-2", category: "Rent", description: "Hillmarton rent", amount: 2100, currency: "GBP", amountPeriod: "month", relatedHouse: "hillmarton" },
  ],
  expenseRecords: [
    { id: "ex-1", category: "Mortgage", description: "Hillmarton mortgage", amount: 1380.42, currency: "GBP", amountPeriod: "month", relatedHouse: "hillmarton" },
    { id: "ex-2", category: "Utility", description: "Electricity and gas (CLP + Towngas)", amount: 1450, currency: "HKD", amountPeriod: "month", relatedHouse: "morrison" },
    { id: "ex-3", category: "Insurance", description: "Family health cover", amount: 28800, currency: "HKD", amountPeriod: "year" },
    { id: "ex-4", category: "Education", description: "School fees", amount: 165000, currency: "HKD", amountPeriod: "year", isAllocate: true },
    { id: "ex-5", category: "Helper", description: "Domestic helper salary and levy", amount: 5200, currency: "HKD", amountPeriod: "month" },
  ],
  expenseIncomeAllocationPercents: { taxOnIncomePercent: 15, investmentOnIncomePercent: 10, savingOnIncomePercent: 5 },
  investmentRecords: [
    { id: "iv-1", category: "Real Estate", currency: "GBP", assetType: "Fixed", provider: "Hillmarton Road", principalAmount: 415000, relatedHouse: "hillmarton", currentValue: 512000, lastUpdated: dateDaysAgo(120) },
    { id: "iv-2", category: "ETF", currency: "USD", assetType: "Liquid", provider: "Interactive Brokers", principalAmount: 42000, unit: 310, ticker: "US:VOO", lastUpdated: dateDaysAgo(2) },
    { id: "iv-3", category: "Crypto", currency: "USD", assetType: "Liquid", provider: "Coinbase", principalAmount: 61000, unit: 0.85, cryptoCurrency: "BTC", lastUpdated: dateDaysAgo(2) },
    { id: "iv-4", category: "Fixed Term Deposit", currency: "HKD", assetType: "Fixed", provider: "HSBC 12-month", principalAmount: 300000, lastUpdated: dateDaysAgo(45) },
  ],
  savingsRecords: [
    { id: "sv-1", deposit: "Emergency fund", assetType: "Liquid", description: "Instant access", value: 180000, currency: "HKD" },
    { id: "sv-2", deposit: "Premium Bonds", assetType: "Liquid", description: "NS&I", value: 25000, currency: "GBP" },
  ],
  pensionRecords: [
    { id: "pn-1", fund: "MPF — Manulife", description: "Employer + employee contributions", value: 486000, currency: "HKD", lastUpdated: dateDaysAgo(20) },
    { id: "pn-2", fund: "UK SIPP", description: "Vanguard LifeStrategy 80", value: 91000, currency: "GBP", lastUpdated: dateDaysAgo(200) },
  ],
  accountRecords: [
    { id: "ac-1", description: "HSBC HK current", accountType: "Bank Account", billingCycleDay: 1, recordedValue: 128430.5, currency: "HKD", lastUpdated: dateDaysAgo(1) },
    { id: "ac-2", description: "Monzo", accountType: "Bank Account", billingCycleDay: 1, recordedValue: 3120.12, currency: "GBP", lastUpdated: dateDaysAgo(1) },
    { id: "ac-3", description: "Amex Platinum", accountType: "Credit Card", billingCycleDay: 14, recordedValue: 18250, lastStatementAmount: 16400, currency: "HKD", lastUpdated: dateDaysAgo(95) },
    { id: "ac-4", description: "Revolut", accountType: "Debit Card", billingCycleDay: 28, recordedValue: 640, currency: "EUR", lastUpdated: dateDaysAgo(4) },
  ],
  liabilityRecords: [
    { id: "li-1", description: "Hillmarton mortgage (Nationwide)", liabilityType: "Mortgage", outstandingBalance: 284000, currency: "GBP", interestRatePercent: 4.15, relatedHouse: "hillmarton", lastUpdated: dateDaysAgo(130) },
    { id: "li-2", description: "Car loan", liabilityType: "Loan", outstandingBalance: 96000, currency: "HKD", interestRatePercent: 2.9, lastUpdated: dateDaysAgo(10) },
  ],
  allocationRecords: [
    { expenseId: "ex-4", description: "School fees", monthlyAmount: 13750, accumulatedAmount: 41250, currency: "HKD", lastUpdated: dateDaysAgo(6) },
    { expenseId: "custom-1", description: "Japan trip", monthlyAmount: 0, accumulatedAmount: 22000, currency: "HKD", isCustomAllocation: true, lastUpdated: dateDaysAgo(30) },
    { expenseId: "custom-2", description: "Retirement top-up", monthlyAmount: 0, accumulatedAmount: 15000, currency: "HKD", isCustomAllocation: true, isPension: true, lastUpdated: dateDaysAgo(30) },
  ],
};

export const siuTinDeiBookFixture: HouseFinanceData = {
  defaultCurrency: "HKD",
  float: { amount: 0, currency: "HKD" },
  lines: [
    { id: "std-1", dateUtc: isoDaysAgo(2), type: "income", description: "Listing plan — Little Explorers", netAmount: 1200, vat: 0, currency: "HKD", grossAmount: 1200 },
    { id: "std-2", dateUtc: isoDaysAgo(6), type: "expenditure", description: "AWS — August", netAmount: 312.4, vat: 0, currency: "USD", grossAmount: 312.4, sourceAssetKeys: ["uploads/siu-tin-dei/aws-2026-08.pdf"] },
    { id: "std-3", dateUtc: isoDaysAgo(12), type: "expenditure", description: "Apple Developer Program", netAmount: 99, vat: 0, currency: "USD", grossAmount: 99 },
  ],
};

export const lxSoftwareBookFixture: HouseFinanceData = {
  defaultCurrency: "HKD",
  float: { amount: 0, currency: "HKD" },
  lines: [
    { id: "lx-1", dateUtc: isoDaysAgo(1), type: "income", description: "Consulting — invoice 2026-031", netAmount: 48000, vat: 0, currency: "HKD", grossAmount: 48000 },
    { id: "lx-2", dateUtc: isoDaysAgo(15), type: "expenditure", description: "Company secretary annual fee", netAmount: 3800, vat: 0, currency: "HKD", grossAmount: 3800 },
  ],
};

export const assetsFixture: readonly AdminAssetMeta[] = [
  { pk: "ASSET#uploads/hillmarton/2026-08-boiler-service.pdf", sk: "META", size: 182_331, uploadedAt: isoDaysAgo(9), fileName: "2026-08-boiler-service.pdf", house: "hillmarton" },
  { pk: "ASSET#uploads/siu-tin-dei/aws-2026-08.pdf", sk: "META", size: 96_004, uploadedAt: isoDaysAgo(6), fileName: "aws-2026-08.pdf", house: "siu-tin-dei" },
  { pk: "ASSET#uploads/morrison/management-fee-notice.jpg", sk: "META", size: 1_204_112, uploadedAt: isoDaysAgo(40), fileName: "management-fee-notice.jpg", house: "morrison" },
];

export const bankingFixture: BankSyncState = {
  enabled: true,
  callbackPath: "/banking/callback",
  sessions: [
    {
      sessionId: "sess-monzo",
      bankName: "Monzo",
      bankCountry: "GB",
      validUntil: isoDaysAgo(-9),
      createdAt: isoDaysAgo(81),
      accounts: [{ uid: "acct-monzo-1", name: "Monzo current", identifier: "04-00-04 ••••1234", currency: "GBP" }],
    },
    {
      sessionId: "sess-revolut",
      bankName: "Revolut",
      bankCountry: "IE",
      validUntil: isoDaysAgo(-150),
      createdAt: isoDaysAgo(30),
      accounts: [
        { uid: "acct-rev-eur", product: "Personal", identifier: "IE•••• 7781", currency: "EUR" },
        { uid: "acct-rev-gbp", product: "Personal", identifier: "GB•••• 0091", currency: "GBP" },
      ],
    },
  ],
  mappings: [
    { accountUid: "acct-monzo-1", accountRecordId: "ac-2" },
    { accountUid: "acct-rev-eur", accountRecordId: "ac-4" },
  ],
  lastSync: {
    at: isoDaysAgo(0),
    results: [
      { accountUid: "acct-monzo-1", accountRecordId: "ac-2", status: "ok", balance: 3120.12, currency: "GBP", balanceType: "interimAvailable" },
      { accountUid: "acct-rev-eur", accountRecordId: "ac-4", status: "error", message: "Consent requires re-authentication" },
    ],
  },
};

const toolsConfig: BoardToolsConfig = {
  enabled: true,
  globalMode: "propose",
  matrix: Object.fromEntries(
    BOARD_TOOL_DEFINITIONS.map((tool) => [
      tool.id,
      Object.fromEntries(BOARD_PERSONA_DEFAULTS.map((p, i) => [p.id, i % 3 === 0 ? "propose" : "read"])),
    ]),
  ),
  allowList: ["owner@example.com", "@siutindei.com"],
  spendCaps: { metaAdsDailyUsd: 10, metaAdsMonthlyUsd: 50 },
};

export const boardMeetingsFixture: readonly BoardMeetingSummary[] = [
  {
    meetingId: "mtg-3",
    status: "succeeded",
    mode: "standup",
    chair: "ceo",
    topic: "",
    trigger: "schedule:morning",
    phase: "done",
    phases: ["agenda", "round", "minutes"],
    createdAt: isoDaysAgo(0),
    updatedAt: isoDaysAgo(0),
    headline: "Ship the provider onboarding form before chasing more listings",
    actionCount: 4,
    usage: { promptTokens: 18200, completionTokens: 3900, totalTokens: 22100, cost: 0.41 },
  },
  {
    meetingId: "mtg-2",
    status: "failed",
    mode: "deepDive",
    chair: "cto",
    topic: "Search relevance and ranking for activity listings",
    trigger: "manual",
    phase: "round",
    phases: ["agenda", "round", "minutes"],
    createdAt: isoDaysAgo(2),
    updatedAt: isoDaysAgo(2),
    headline: "",
    actionCount: 0,
    usage: { promptTokens: 6000, completionTokens: 800, totalTokens: 6800, cost: 0.12 },
    errorMessage: "Daily budget exhausted",
  },
  {
    meetingId: "mtg-1",
    status: "succeeded",
    mode: "standup",
    chair: "ceo",
    topic: "",
    trigger: "schedule:evening",
    phase: "done",
    phases: ["agenda", "round", "minutes"],
    createdAt: isoDaysAgo(1),
    updatedAt: isoDaysAgo(1),
    headline: "Pricing page copy and FPS reference on invoices",
    actionCount: 2,
    usage: { promptTokens: 15100, completionTokens: 3100, totalTokens: 18200, cost: 0.34 },
  },
];

export const boardActionsFixture: readonly BoardAction[] = [
  {
    actionId: "act-1",
    title: "Publish provider onboarding form",
    detail: "Replace the Google Form with the in-app flow so listings get structured data from day one.",
    persona: "cpo",
    priority: "now",
    effort: "M",
    metric: "providers onboarded / week",
    dependsOn: [],
    status: "open",
    note: "",
    meetingId: "mtg-3",
    reaffirmedByMeetingIds: ["mtg-1"],
    dueAt: isoDaysAgo(-5),
    createdAt: isoDaysAgo(1),
    updatedAt: isoDaysAgo(0),
  },
  {
    actionId: "act-2",
    title: "Add FPS reference to invoice PDF",
    detail: "Payments arrive without a reference; matching is manual.",
    persona: "cfo",
    priority: "next",
    effort: "S",
    metric: "unmatched payments",
    dependsOn: [],
    status: "open",
    note: "",
    meetingId: "mtg-1",
    reaffirmedByMeetingIds: [],
    dueAt: null,
    createdAt: isoDaysAgo(1),
    updatedAt: isoDaysAgo(1),
  },
  {
    actionId: "act-3",
    title: "Instagram launch teaser",
    detail: "Three posts announcing the September provider cohort.",
    persona: "cmo",
    priority: "later",
    effort: "S",
    metric: "profile visits",
    dependsOn: ["act-1"],
    status: "done",
    note: "Posted 2 Sep.",
    meetingId: "mtg-1",
    reaffirmedByMeetingIds: [],
    dueAt: null,
    createdAt: isoDaysAgo(3),
    updatedAt: isoDaysAgo(0),
  },
];

export const boardApprovalsFixture: readonly BoardApproval[] = [
  {
    approvalId: "apr-1",
    status: "pending",
    personaId: "cmo",
    displayName: "CMO",
    toolId: "mail",
    toolLabel: "Mail",
    op: "mail_send",
    kind: "write",
    arguments: {
      to: ["contact#3"],
      subject: "Your Siu Tin Dei listing is live",
      body: "Hi there,\n\nYour listing is now visible to parents. Reply to this email if anything looks wrong.\n\nSiu Tin Dei",
    },
    summary: "Send launch confirmation to a newly onboarded provider",
    reason: "Recipient is outside the allow-list",
    context: { kind: "meeting", meetingId: "mtg-3", phase: "round" },
    createdAt: isoDaysAgo(0),
    updatedAt: isoDaysAgo(0),
  },
];

export const boardToolsFixture: BoardToolsPayload = {
  config: toolsConfig,
  effective: toolsConfig.matrix,
  enabled: true,
  envDisabled: false,
  registry: BOARD_TOOL_DEFINITIONS.map((tool) => ({
    id: tool.id,
    label: tool.label,
    description: tool.description,
    maxLevel: "act",
    operations: [],
  })),
  defaults: toolsConfig,
  repoWriteEnabled: false,
  mailSendEnabled: false,
  mailDomain: "siutindei.com",
  searchConfigured: true,
  dataApiConfigured: true,
  metaConfigured: false,
  storesConfigured: true,
  webConfigured: true,
};

export const boardOverviewFixture: BoardOverview = {
  settings: {
    schedule: { morningEnabled: true, eveningEnabled: true },
    defaultMode: "standup",
    defaultChair: "ceo",
    shareFinanceSummary: true,
    shareRepoSnapshot: true,
    models: { chat: "", standup: "", deepDive: "" },
    dailyBudgetUsd: 15,
    tools: toolsConfig,
  },
  charter: {
    vision: "Siu Tin Dei is the place Hong Kong parents go first to find and book activities for their children.",
    mission: "Get to a live, revenue-generating product on a founder's evenings and weekends.",
  },
  brief: { markdown: "# Brief\n\nSeptember cohort: 12 providers onboarded, 3 paying.\n\n- Pricing page live\n- FPS reference pending" },
  members: BOARD_PERSONA_DEFAULTS.map((p) => ({
    id: p.id,
    title: p.title,
    shortName: p.shortName,
    focusAreas: p.focusAreas,
    kpisOwned: p.kpisOwned,
    vision: p.vision,
    mission: p.mission,
    mandate: p.mandate,
    displayName: p.shortName,
    defaults: { vision: p.vision, mission: p.mission, mandate: p.mandate },
    isOverridden: { vision: false, mission: false, mandate: false, displayName: false },
    profileHash: `hash-${p.id}`,
  })),
  chairDefault: "ceo",
  openActionCount: 2,
  runningMeeting: null,
  latestMeeting: boardMeetingsFixture[0],
  usageToday: { promptTokens: 18200, completionTokens: 3900, totalTokens: 22100, cost: 0.41, calls: 9, budgetUsd: 15 },
  models: { chat: "openai/gpt-4.1-mini", standup: "openai/gpt-4.1", deepDive: "anthropic/claude-sonnet-4" },
  repoSnapshot: {
    repo: "lx-software-ltd/siutindei",
    fetchedAt: isoDaysAgo(0),
    openIssuesCount: 14,
    docs: ["README.md", "docs/architecture.md"],
    commits: 25,
    ci: { name: "Test", status: "completed", conclusion: "success" },
    chars: 48_000,
  },
  repoSnapshotEnabled: true,
  repoWriteEnabled: false,
  repo: "lx-software-ltd/siutindei",
  pendingApprovalCount: 1,
  toolsEnabled: true,
  unreadMailCount: 3,
  overdueInvoiceCount: 2,
  mail: { threadCount: 11, unreadCount: 3, domain: "siutindei.com", sendEnabled: false, inboundAddress: "siutindei-board@mail.example.com" },
  receivables: { outstandingHkd: 7200, overdue: 2 },
};

export const boardReceivablesFixture: BoardReceivablesPayload = {
  configured: true,
  invoices: [],
  subscriptions: [
    { id: "sub-1", organization_id: "org-1", status: "active", plan_name: "Listing Plus", price_hkd: 1200, renews_on: dateDaysAgo(-20), payer_contact: "contact#1" },
    { id: "sub-2", organization_id: "org-2", status: "past_due", plan_name: "Listing Basic", price_hkd: 600, renews_on: dateDaysAgo(3), payer_contact: "contact#2" },
  ],
  aging: {
    asOf: dateDaysAgo(0),
    outstandingHkd: 7200,
    dso: 19,
    buckets: {
      current: [
        { id: "inv-1", number: "STD-2026-031", amount_hkd: 1200, status: "issued", due_on: dateDaysAgo(-4), fps_reference: "STD2026031", subscription_id: "sub-1" },
      ],
      d7: [
        { id: "inv-2", number: "STD-2026-027", amount_hkd: 600, status: "overdue", due_on: dateDaysAgo(9), fps_reference: "STD2026027", subscription_id: "sub-2" },
      ],
      d21: [
        { id: "inv-3", number: "STD-2026-019", amount_hkd: 5400, status: "overdue", due_on: dateDaysAgo(24), fps_reference: "STD2026019" },
      ],
      d35: [],
    },
  },
};

export const awsUsageFixture: AwsBillingPayload = {
  from: "2026-08-01",
  to: "2026-08-31",
  currency: "USD",
  payer: { id: "lxSoftware", label: "LX Software" },
  source: "cost-explorer",
  costAllocationTags: ["Organization", "Project"],
  total: { usd: 858.69 },
  companies: [
    {
      id: "siuTinDei",
      label: "Siu Tin Dei",
      usd: 420.64,
      share: 0.4899,
      projects: [{ id: "Siu Tin Dei", label: "Siu Tin Dei", usd: 420.64 }],
    },
    {
      id: "evolveSprouts",
      label: "Evolve Sprouts",
      usd: 434.12,
      share: 0.5056,
      projects: [
        { id: "Backend", label: "Backend", usd: 432.37 },
        { id: "Public Website", label: "Public Website", usd: 0.91 },
        { id: "Marketing", label: "Marketing", usd: 0.4 },
        { id: "(untagged)", label: "(untagged)", usd: 0.4 },
        { id: "Admin Website", label: "Admin Website", usd: 0.04 },
      ],
    },
    {
      id: "lxSoftware",
      label: "LX Software",
      usd: 3.88,
      share: 0.0045,
      projects: [
        { id: "(untagged)", label: "(untagged)", usd: 1.82 },
        { id: "Admin Console", label: "Admin Console", usd: 1.65 },
        { id: "Admin Portal", label: "Admin Portal", usd: 0.4 },
        { id: "Public Website", label: "Public Website", usd: 0.01 },
      ],
    },
    {
      id: "unallocated",
      label: "Unallocated",
      usd: 0.05,
      share: 0.0001,
      projects: [{ id: "(untagged)", label: "(untagged)", usd: 0.05 }],
    },
  ],
};

export const openrouterUsageFixture: OpenRouterUsagePayload = {
  from: "2026-09-01",
  to: "2026-09-08",
  currency: "USD",
  payer: { id: "lxSoftware", label: "LX Software" },
  total: {
    promptTokens: 41200,
    completionTokens: 9100,
    totalTokens: 37300,
    cost: 2.15,
    calls: 18,
  },
  apps: [
    {
      id: "statement-parser",
      label: "Statement parser",
      title: "LX Admin - Statement parser",
      referer: "https://admin.lx-software.com/finance/parse-statement",
      repo: "lx-software-ltd/lx-software",
      keyName: "lxsoftware:statement-parser",
      meteredHere: true,
      promptTokens: 23000,
      completionTokens: 5200,
      totalTokens: 15200,
      cost: 0.74,
      calls: 9,
      owners: [
        {
          id: "hillmarton",
          label: "32 Hillmarton",
          promptTokens: 4200,
          completionTokens: 400,
          totalTokens: 4600,
          cost: 0.18,
          calls: 2,
        },
        {
          id: "lxSoftware",
          label: "LX Software",
          promptTokens: 8800,
          completionTokens: 800,
          totalTokens: 5000,
          cost: 0.31,
          calls: 3,
        },
        {
          id: "siuTinDei",
          label: "Siu Tin Dei",
          promptTokens: 10000,
          completionTokens: 4000,
          totalTokens: 5600,
          cost: 0.25,
          calls: 4,
        },
      ],
    },
    {
      id: "executive-board",
      label: "Executive Board",
      title: "LX Admin - Executive Board",
      referer: "https://admin.lx-software.com/siu-tin-dei/board",
      repo: "lx-software-ltd/lx-software",
      keyName: "lxsoftware:executive-board",
      meteredHere: true,
      promptTokens: 18200,
      completionTokens: 3900,
      totalTokens: 22100,
      cost: 1.41,
      calls: 9,
      owners: [
        {
          id: "siuTinDei",
          label: "Siu Tin Dei",
          promptTokens: 18200,
          completionTokens: 3900,
          totalTokens: 22100,
          cost: 1.41,
          calls: 9,
        },
      ],
    },
    {
      id: "evolvesprouts",
      label: "Evolve Sprouts",
      title: "Evolve Sprouts",
      referer: "https://evolvesprouts.com",
      repo: "lx-software-ltd/evolvesprouts",
      keyName: "lxsoftware:evolvesprouts",
      meteredHere: false,
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
      cost: 0,
      calls: 0,
      owners: [],
    },
    {
      id: "siutindei",
      label: "Siu Tin Dei",
      title: "Siu Tin Dei",
      referer: "https://siutindei.com",
      repo: "lx-software-ltd/siutindei",
      keyName: "lxsoftware:siutindei",
      meteredHere: false,
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
      cost: 0,
      calls: 0,
      owners: [],
    },
  ],
};
