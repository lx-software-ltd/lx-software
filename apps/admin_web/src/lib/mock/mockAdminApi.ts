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
  boardToolsFixture,
  financeFixture,
  lxSoftwareBookFixture,
  openrouterUsageFixture,
  awsUsageFixture,
  siuTinDeiBookFixture,
} from "./fixtures";

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
};

const state: MockState = {
  finance: structuredClone(financeFixture) as FinancePersistedState,
  books: {
    "siu-tin-dei": structuredClone(siuTinDeiBookFixture) as HouseFinanceData,
    "lx-software": structuredClone(lxSoftwareBookFixture) as HouseFinanceData,
  },
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

  return notFound(p);
}
