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
  boardHoldsFixture,
  boardStaffFixture,
  boardTaskDetailFixture,
  boardTasksFixture,
  boardToolsFixture,
  financeFixture,
  lxSoftwareBookFixture,
  siuTinDeiBookFixture,
} from "./fixtures";
import { DEFAULT_BOARD_BOUNDARIES, type BoardBoundaries, type BoardHold, type BoardSeat, type BoardTask } from "../boardModel";

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
  if (p === `${board}/approvals`) return json({ approvals: boardApprovalsFixture });
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
      ramp: [{ classKey: "publish:facebook", actions: 1, vetoes: 0, rate: 0, eligibleForPromotion: false, shouldDemote: false }],
    });
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
