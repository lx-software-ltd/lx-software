/**
 * In-browser stand-in for the admin API, enabled with `VITE_ADMIN_MOCK=1`
 * (`npm run dev:mock`). Serves the fixtures in fixtures.ts, keeps PUT results
 * in memory for the session, and signs the SPA in with a fake admin ID token so
 * every page renders with data and no AWS stack.
 *
 * Never enable in a production build: `isAdminMockEnabled()` is the only gate.
 */
import { saveTokensFromOAuthResponse } from "../auth";
import { isAdminMockEnabled } from "./isAdminMockEnabled";
import type { HouseFinanceData, FinancePersistedState } from "../financeModel";
import {
  assetsFixture,
  bankingFixture,
  boardActionsFixture,
  boardApprovalsFixture,
  boardMeetingsFixture,
  boardOverviewFixture,
  boardReceivablesFixture,
  boardBreakersFixture,
  boardHoldsFixture,
  boardLessonsFixture,
  boardReviewFixture,
  boardStaffFixture,
  boardTaskDetailFixture,
  boardTasksFixture,
  boardToolsFixture,
  boardWatchesFixture,
  boardChangesFixture,
  boardProspectsFixture,
  boardOutreachStatsFixture,
  boardSequenceFixture,
  boardContentFixture,
  financeFixture,
  lxSoftwareBookFixture,
  openrouterUsageFixture,
  awsUsageFixture,
  siuTinDeiBookFixture,
} from "./fixtures";
import {
  DEFAULT_BOARD_BOUNDARIES,
  type BoardApproval,
  type BoardBoundaries,
  type BoardBreaker,
  type BoardHold,
  type BoardLesson,
  type BoardSeat,
  type BoardTask,
  type BoardWatch,
  type BoardProspect,
  type BoardSequence,
  type BoardContentItem,
} from "../boardModel";

export { isAdminMockEnabled };

function base64Url(input: string): string {
  return btoa(input).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Unsigned JWT that satisfies the client-side admin-group check only. */
export function buildMockIdToken(): string {
  const now = Math.floor(Date.now() / 1000);
  const header = base64Url(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64Url(
    JSON.stringify({
      sub: "mock-admin",
      email: "mock.admin@example.com",
      "cognito:groups": ["admin"],
      iat: now,
      auth_time: now,
      exp: now + 12 * 3600,
    }),
  );
  return `${header}.${payload}.mock`;
}

export function installAdminMockSession(): void {
  saveTokensFromOAuthResponse({
    id_token: buildMockIdToken(),
    access_token: "mock-access",
    refresh_token: "mock-refresh",
    expires_in: 12 * 3600,
  });
}

type MockState = {
  finance: FinancePersistedState;
  books: Record<string, HouseFinanceData>;
  seats: BoardSeat[];
  tasks: BoardTask[];
  holds: BoardHold[];
  boundaries: BoardBoundaries;
  lessons: BoardLesson[];
  breakers: BoardBreaker[];
  watches: BoardWatch[];
  prospects: BoardProspect[];
  sequences: Record<string, BoardSequence>;
  content: BoardContentItem[];
  approvals: BoardApproval[];
};

const state: MockState = {
  finance: structuredClone(financeFixture) as FinancePersistedState,
  books: {
    "siu-tin-dei": structuredClone(siuTinDeiBookFixture) as HouseFinanceData,
    "lx-software": structuredClone(lxSoftwareBookFixture) as HouseFinanceData,
  },
  seats: structuredClone(boardStaffFixture.seats) as BoardSeat[],
  tasks: structuredClone(boardTasksFixture),
  holds: structuredClone(boardHoldsFixture) as BoardHold[],
  boundaries: structuredClone(DEFAULT_BOARD_BOUNDARIES),
  lessons: structuredClone(boardLessonsFixture) as BoardLesson[],
  breakers: structuredClone(boardBreakersFixture) as BoardBreaker[],
  watches: structuredClone(boardWatchesFixture) as BoardWatch[],
  prospects: structuredClone(boardProspectsFixture) as BoardProspect[],
  sequences: {},
  content: structuredClone(boardContentFixture) as BoardContentItem[],
  approvals: structuredClone(boardApprovalsFixture) as BoardApproval[],
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function notFound(path: string): Response {
  return json({ message: `Mock API has no route for ${path}` }, 404);
}

function parseBody(init: RequestInit): Record<string, unknown> {
  if (typeof init.body !== "string" || !init.body) return {};
  try {
    return JSON.parse(init.body) as Record<string, unknown>;
  } catch {
    return {};
  }
}

const FINANCE_LIST_KEYS: Readonly<Record<string, keyof FinancePersistedState>> = {
  investments: "investmentRecords",
  savings: "savingsRecords",
  pension: "pensionRecords",
  accounts: "accountRecords",
  liabilities: "liabilityRecords",
  allocations: "allocationRecords",
  income: "incomeRecords",
  expenses: "expenseRecords",
};

function fxRates(url: URL): Response {
  const base = url.searchParams.get("base") ?? "HKD";
  const quotes = (url.searchParams.get("quotes") ?? "").split(",").filter(Boolean);
  // Approximate cross rates expressed in HKD, enough for totals to look plausible.
  const inHkd: Record<string, number> = { HKD: 1, USD: 7.8, GBP: 9.9, EUR: 8.5, CNY: 1.08, SGD: 5.8, AED: 2.12 };
  const baseHkd = inHkd[base] ?? 1;
  const date = new Date().toISOString().slice(0, 10);
  return json(
    quotes.map((quote) => ({ date, base, quote, rate: (inHkd[quote] ?? 1) / baseHkd })),
  );
}

function overlayUsageRange<T extends { from: string; to: string }>(
  url: URL,
  fixture: T,
): T {
  const from = url.searchParams.get("from");
  const to = url.searchParams.get("to");
  if (!from && !to) return fixture;
  return { ...fixture, from: from || fixture.from, to: to || fixture.to };
}

function quotes(url: URL): Response {
  const symbols = (url.searchParams.get("symbols") ?? "").split(",").filter(Boolean);
  const prices: Record<string, { price: number; currency: string }> = {
    "US:VOO": { price: 512.4, currency: "USD" },
    BTC: { price: 71_250, currency: "USD" },
  };
  return json(
    symbols.map((symbol) => {
      const hit = prices[decodeURIComponent(symbol)];
      return hit
        ? { symbol, yahooSymbol: symbol, price: hit.price, currency: hit.currency }
        : { symbol, yahooSymbol: symbol, error: "No mock quote" };
    }),
  );
}

export async function mockAdminFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const url = new URL(path, "http://mock.local");
  const p = url.pathname;

  if (p === "/health") return json({ status: "ok" });
  if (p === "/me") return json({ sub: "mock-admin", email: "mock.admin@example.com" });
  if (p === "/openrouter/usage") return json(overlayUsageRange(url, openrouterUsageFixture));
  if (p === "/aws/usage") return json(overlayUsageRange(url, awsUsageFixture));
  if (p === "/aws/usage.pdf") {
    const body =
      "%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\nlx-software-aws-mock\n";
    return new Response(body, {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="lx-software-aws-2026-08.pdf"',
      },
    });
  }
  if (p === "/finance" && method === "GET") return json(state.finance);
  if (p === "/finance/quotes") return quotes(url);
  if (p === "/fx/v2/rates") return fxRates(url);
  if (p === "/finance/hillmarton" || p === "/finance/morrison") {
    const house = p.slice("/finance/".length) as "hillmarton" | "morrison";
    if (method === "PUT") {
      const data = parseBody(init) as unknown as HouseFinanceData;
      state.finance = { ...state.finance, [house]: data };
    }
    return json({ data: state.finance[house] });
  }
  if (p.startsWith("/finance/")) {
    const listKey = FINANCE_LIST_KEYS[p.slice("/finance/".length)];
    if (listKey) {
      if (method === "PUT") {
        const body = parseBody(init);
        state.finance = {
          ...state.finance,
          [listKey]: body[listKey] ?? state.finance[listKey],
          ...(body.expenseIncomeAllocationPercents
            ? { expenseIncomeAllocationPercents: body.expenseIncomeAllocationPercents }
            : {}),
        } as FinancePersistedState;
      }
      return json({
        [listKey]: state.finance[listKey],
        expenseIncomeAllocationPercents: state.finance.expenseIncomeAllocationPercents,
      });
    }
  }

  const book = state.books[p.slice(1)];
  if (book) {
    if (method === "PUT") {
      state.books[p.slice(1)] = parseBody(init) as unknown as HouseFinanceData;
    }
    return json({ data: state.books[p.slice(1)] });
  }

  if (p === "/records") return json({ items: assetsFixture, nextCursor: null });
  if (p === "/assets") return json({ items: assetsFixture, nextCursor: null });
  if (p === "/assets/download-url") return json({ url: "about:blank" });
  if (p === "/assets/delete") return json({ ok: true });

  if (p === "/banking") return json(bankingFixture);
  if (p === "/banking/banks") {
    return json({
      banks: [
        { name: "Monzo", country: "GB", beta: false, maximumConsentValidity: 90 * 86_400 },
        { name: "Barclays", country: "GB", beta: false, maximumConsentValidity: 90 * 86_400 },
      ],
    });
  }
  if (p === "/banking/sync") return json(bankingFixture.lastSync);
  if (p === "/banking/mappings") return json({ mappings: parseBody(init).mappings ?? bankingFixture.mappings });

  const board = "/siu-tin-dei/board";
  if (p === board) return json(boardOverviewFixture);
  if (p === `${board}/actions`) return json({ actions: boardActionsFixture });
  if (p === `${board}/approvals`) return json({ approvals: state.approvals });
  if (p === `${board}/meetings`) return json({ meetings: boardMeetingsFixture });
  if (p === `${board}/tools`) return json(boardToolsFixture);
  if (p === `${board}/tools/calls`) return json({ calls: [] });
  if (p === `${board}/updates`) return json({ updates: [] });
  if (p === `${board}/receivables`) return json(boardReceivablesFixture);
  if (p === `${board}/mail`) {
    return json({ threads: [], total: 0, mailboxes: [], status: boardOverviewFixture.mail });
  }
  if (p === `${board}/staff`) {
    return json({
      ...boardStaffFixture,
      seats: state.seats,
      counts: countsFromTasks(state.tasks),
    });
  }
  if (p.startsWith(`${board}/staff/`)) {
    const seatId = p.slice(`${board}/staff/`.length);
    const idx = state.seats.findIndex((s) => s.id === seatId);
    if (idx < 0) return json({ message: "Unknown staff seat" }, 404);
    if (method === "DELETE") {
      const defaults = boardStaffFixture.seats.find((s) => s.id === seatId);
      if (defaults) state.seats[idx] = structuredClone(defaults);
      return json({ seat: state.seats[idx] });
    }
    if (method === "PUT") {
      const body = parseBody(init);
      const current = state.seats[idx];
      state.seats[idx] = {
        ...current,
        displayName: typeof body.displayName === "string" && body.displayName ? body.displayName : current.displayName,
        brief: typeof body.brief === "string" && body.brief ? body.brief : current.brief,
        isActive: typeof body.isActive === "boolean" ? body.isActive : current.isActive,
        modelTier: body.modelTier === "senior" || body.modelTier === "desk" ? body.modelTier : current.modelTier,
        isOverridden: {
          ...current.isOverridden,
          displayName: Boolean(body.displayName),
          brief: Boolean(body.brief),
          isActive: body.isActive !== undefined,
          modelTier: Boolean(body.modelTier),
        },
      };
      return json({ seat: state.seats[idx] });
    }
  }
  if (p === `${board}/tasks`) {
    if (method === "POST") {
      const body = parseBody(init);
      const created: BoardTask = {
        ...boardTasksFixture[0],
        taskId: `task-${state.tasks.length + 1}`,
        status: "queued",
        assignee: String(body.assignee || "cfo"),
        assigneeKind: String(body.assignee || "").includes("-") ? "seat" : "persona",
        brief: String(body.brief || "Untitled"),
        deliverableType: (body.deliverableType as BoardTask["deliverableType"]) || "markdown",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      state.tasks = [created, ...state.tasks];
      return json({ task: created }, 201);
    }
    return json({ tasks: state.tasks, counts: countsFromTasks(state.tasks) });
  }
  if (p.startsWith(`${board}/tasks/`)) {
    const rest = p.slice(`${board}/tasks/`.length).split("/");
    const taskId = rest[0];
    const task = state.tasks.find((t) => t.taskId === taskId);
    if (!task) return json({ message: "Task not found" }, 404);
    if (rest[1] === "cancel" && method === "POST") {
      Object.assign(task, { status: "cancelled", updatedAt: new Date().toISOString() });
      return json({ task });
    }
    if (rest[1] === "review" && method === "POST") {
      const body = parseBody(init);
      Object.assign(task, {
        status: body.verdict === "return" ? "running" : "delivered",
        lastReview: { verdict: body.verdict, notes: body.notes, at: new Date().toISOString() },
        updatedAt: new Date().toISOString(),
      });
      return json({ task });
    }
    return json(boardTaskDetailFixture(taskId) ?? { task, steps: [], reviews: [], deliverable: "", deliverableUrl: "" });
  }
  if (p === `${board}/holds`) {
    return json({ holds: state.holds.filter((h) => h.status === "scheduled") });
  }
  if (p === `${board}/holds/veto-class` && method === "POST") {
    const body = parseBody(init);
    const classKey = String(body.classKey || "");
    state.holds = state.holds.map((h) =>
      h.classKey === classKey && h.status === "scheduled" ? { ...h, status: "vetoed" as const } : h,
    );
    return json({ holds: state.holds.filter((h) => h.status === "vetoed" && h.classKey === classKey) });
  }
  if (p.startsWith(`${board}/holds/`) && p.endsWith("/veto") && method === "POST") {
    const holdId = p.slice(`${board}/holds/`.length, -"/veto".length);
    const idx = state.holds.findIndex((h) => h.holdId === holdId);
    if (idx < 0) return json({ message: "Hold not found" }, 404);
    state.holds[idx] = { ...state.holds[idx], status: "vetoed" };
    return json({ hold: state.holds[idx] });
  }
  if (p === `${board}/boundaries` && method === "PUT") {
    state.boundaries = parseBody(init) as BoardBoundaries;
    return json({ boundaries: state.boundaries });
  }
  if (p === `${board}/ramp`) {
    return json({
      ramp: [{ classKey: "publish:facebook", actions: 32, vetoes: 0, rate: 0, eligibleForPromotion: true, shouldDemote: false }],
    });
  }
  if (p.startsWith(`${board}/ramp/`) && p.endsWith("/promote") && method === "POST") {
    return json({ classKey: decodeURIComponent(p.slice(`${board}/ramp/`.length, -"/promote".length)), holdOverrides: { "publish:facebook": 0 } });
  }
  if (p === `${board}/code/staging`) {
    return json({
      staging: {
        status: "ahead",
        behindBy: 0,
        aheadBy: 1,
        canPromote: true,
        commits: [{ sha: "a1b2c3d4", message: "board: #42 add booking" }],
      },
    });
  }
  if (p === `${board}/code/promote` && method === "POST") {
    const now = new Date().toISOString();
    const approval: BoardApproval = {
      approvalId: `appr-promote-${state.approvals.length + 1}`,
      status: "pending",
      personaId: "cto",
      displayName: "CTO",
      toolId: "code",
      toolLabel: "Code",
      op: "code_promote",
      kind: "write",
      arguments: { kind: "production" },
      summary: "Open a staging→main PR for board: #42 add booking",
      reason: "code_promote always queues an Approval",
      context: { kind: "review" },
      createdAt: now,
      updatedAt: now,
    };
    state.approvals = [approval, ...state.approvals];
    return json(
      {
        approval,
        preview: { status: "ahead", aheadBy: 1, behindBy: 0, canPromote: true, commits: [] },
      },
      201,
    );
  }
  if (p === `${board}/review`) {
    return json({ review: boardReviewFixture });
  }
  if (p.startsWith(`${board}/review/sample/`) && p.endsWith("/wrong") && method === "POST") {
    const callId = decodeURIComponent(p.slice(`${board}/review/sample/`.length, -"/wrong".length));
    const lesson: BoardLesson = {
      lessonId: `lsn-${state.lessons.length + 1}`,
      kind: "correction",
      subject: "cmo",
      classKey: "publish:facebook",
      what: callId,
      instruction: "Do not repeat this post without a district and a date.",
      confirmed: false,
      createdAt: new Date().toISOString(),
    };
    state.lessons = [lesson, ...state.lessons];
    return json({ lesson });
  }
  if (p === `${board}/lessons`) {
    return json({ lessons: state.lessons });
  }
  if (p.startsWith(`${board}/lessons/`) && p.endsWith("/confirm") && method === "POST") {
    const lessonId = decodeURIComponent(p.slice(`${board}/lessons/`.length, -"/confirm".length));
    const body = parseBody(init) as { instruction?: string };
    state.lessons = state.lessons.map((l) =>
      l.lessonId === lessonId ? { ...l, confirmed: true, instruction: body.instruction || l.instruction } : l,
    );
    return json({ lesson: state.lessons.find((l) => l.lessonId === lessonId) });
  }
  if (p.startsWith(`${board}/lessons/`) && p.endsWith("/dismiss") && method === "POST") {
    const lessonId = decodeURIComponent(p.slice(`${board}/lessons/`.length, -"/dismiss".length));
    state.lessons = state.lessons.map((l) => (l.lessonId === lessonId ? { ...l, dismissed: true } : l));
    return json({ lesson: state.lessons.find((l) => l.lessonId === lessonId) });
  }
  if (p === `${board}/breakers`) {
    return json({ breakers: state.breakers });
  }
  if (p.startsWith(`${board}/breakers/`) && p.endsWith("/reset") && method === "POST") {
    const name = decodeURIComponent(p.slice(`${board}/breakers/`.length, -"/reset".length));
    state.breakers = state.breakers.map((b) => (b.name === name ? { ...b, tripped: false, resetAt: new Date().toISOString() } : b));
    return json({ breaker: state.breakers.find((b) => b.name === name) });
  }
  if (p === `${board}/watchlist`) {
    if (method === "POST") {
      const body = parseBody(init);
      const watch: BoardWatch = {
        watchId: `watch-${state.watches.length + 1}`,
        name: String(body.name ?? ""),
        kind: String(body.kind ?? "competitor"),
        urls: Array.isArray(body.urls) ? body.urls.map(String) : [],
        appIds: typeof body.appIds === "object" && body.appIds ? (body.appIds as Record<string, string>) : {},
        createdAt: new Date().toISOString(),
      };
      state.watches = [watch, ...state.watches];
      return json({ watch }, 201);
    }
    return json({
      watches: state.watches,
      latestBrief: { taskId: "task-review", status: "review", summary: "Weekly market brief" },
    });
  }
  if (p.startsWith(`${board}/watchlist/`)) {
    const watchId = decodeURIComponent(p.slice(`${board}/watchlist/`.length));
    const idx = state.watches.findIndex((w) => w.watchId === watchId);
    if (idx < 0) return json({ message: "Watch not found" }, 404);
    if (method === "DELETE") {
      state.watches = state.watches.filter((w) => w.watchId !== watchId);
      return json({ ok: true });
    }
    if (method === "PUT") {
      const body = parseBody(init);
      state.watches[idx] = {
        ...state.watches[idx],
        ...(typeof body.name === "string" ? { name: body.name } : {}),
        ...(typeof body.kind === "string" ? { kind: body.kind } : {}),
        ...(Array.isArray(body.urls) ? { urls: body.urls.map(String) } : {}),
      };
      return json({ watch: state.watches[idx] });
    }
  }
  if (p === `${board}/changes`) {
    return json({ changes: boardChangesFixture });
  }
  if (p === `${board}/prospects`) {
    return json({
      prospects: state.prospects,
      needsContact: state.prospects.filter((row) => row.stage === "qualified" && !row.contact),
      stats: boardOutreachStatsFixture,
    });
  }
  if (p === `${board}/prospects/import` && method === "POST") {
    const body = parseBody(init);
    const lines = String(body.csv ?? "").trim().split("\n").slice(1);
    let created = 0;
    for (const line of lines) {
      const [name, type, district, website, email] = line.split(",");
      if (!name) continue;
      state.prospects = [
        {
          prospectId: `pros-${state.prospects.length + 1}`,
          name,
          type: type || "provider",
          district,
          website,
          email,
          contact: email || null,
          stage: "discovered",
          source: "owner",
        },
        ...state.prospects,
      ];
      created += 1;
    }
    return json({ created, updated: 0, errors: [] });
  }
  if (p.startsWith(`${board}/prospects/`) && p.endsWith("/merge") && method === "POST") {
    const prospectId = decodeURIComponent(p.slice(`${board}/prospects/`.length, -"/merge".length));
    const body = parseBody(init);
    const into = String(body.into ?? "");
    const src = state.prospects.find((row) => row.prospectId === prospectId);
    const destIdx = state.prospects.findIndex((row) => row.prospectId === into);
    if (!src || destIdx < 0) return json({ message: "Prospect not found" }, 404);
    state.prospects[destIdx] = { ...state.prospects[destIdx], name: state.prospects[destIdx].name || src.name };
    state.prospects = state.prospects.map((row) => (row.prospectId === prospectId ? { ...row, stage: "suppressed" } : row));
    return json({ prospect: state.prospects[destIdx] });
  }
  if (p.startsWith(`${board}/prospects/`)) {
    const prospectId = decodeURIComponent(p.slice(`${board}/prospects/`.length));
    const idx = state.prospects.findIndex((row) => row.prospectId === prospectId);
    if (idx < 0) return json({ message: "Prospect not found" }, 404);
    if (method === "PUT") {
      const body = parseBody(init);
      state.prospects[idx] = {
        ...state.prospects[idx],
        ...(typeof body.stage === "string" ? { stage: body.stage } : {}),
        ...(typeof body.contact === "string" ? { contact: body.contact } : {}),
        ...(typeof body.type === "string" ? { type: body.type } : {}),
        ...(typeof body.note === "string" ? { ownerNote: body.note } : {}),
      };
    }
    return json({ prospect: state.prospects[idx] });
  }
  if (p === `${board}/outreach/stats`) {
    return json(boardOutreachStatsFixture);
  }
  if (p.startsWith(`${board}/sequences/`)) {
    const type = decodeURIComponent(p.slice(`${board}/sequences/`.length));
    if (method === "PUT") {
      const body = parseBody(init);
      state.sequences[type] = { type, steps: Array.isArray(body.steps) ? body.steps : [] } as BoardSequence;
      return json({ sequence: state.sequences[type] });
    }
    return json({ sequence: state.sequences[type] ?? boardSequenceFixture(type) });
  }
  if (p === `${board}/content`) {
    if (method === "POST") {
      const body = parseBody(init);
      const item: BoardContentItem = {
        contentId: `cnt-${state.content.length + 1}`,
        status: "drafted",
        channel: String(body.channel || "facebook"),
        pillar: String(body.pillar || "activity spotlight"),
        slotAt: String(body.slotAt || new Date().toISOString()),
        copyEn: String(body.copyEn || ""),
        copyZh: String(body.copyZh || ""),
      };
      state.content = [item, ...state.content];
      return json({ item });
    }
    return json({
      items: state.content,
      assisted: state.content.filter((row) => String(row.channel || "").startsWith("assisted")),
    });
  }
  if (p.includes("/creative/") && p.startsWith(`${board}/content/`)) {
    return json({ url: "https://assets.example/board/content/preview.png", key: "preview.png" });
  }
  if (p.startsWith(`${board}/content/`) && p.endsWith("/render") && method === "POST") {
    const contentId = decodeURIComponent(p.slice(`${board}/content/`.length, -"/render".length));
    const item = state.content.find((row) => row.contentId === contentId);
    if (!item) return json({ message: "Not found" }, 404);
    return json({ item });
  }
  if (p.startsWith(`${board}/content/`)) {
    const contentId = decodeURIComponent(p.slice(`${board}/content/`.length));
    const idx = state.content.findIndex((row) => row.contentId === contentId);
    if (idx < 0) return json({ message: "Not found" }, 404);
    if (method === "PUT") {
      const body = parseBody(init);
      state.content[idx] = { ...state.content[idx], ...body } as BoardContentItem;
    }
    return json({ item: state.content[idx] });
  }

  return notFound(p);
}

function countsFromTasks(tasks: readonly BoardTask[]): Record<string, number> {
  const counts: Record<string, number> = {
    queued: 0,
    running: 0,
    review: 0,
    returned: 0,
    delivered: 0,
    needs_owner: 0,
    failed: 0,
    cancelled: 0,
  };
  for (const task of tasks) counts[task.status] = (counts[task.status] ?? 0) + 1;
  return counts;
}
