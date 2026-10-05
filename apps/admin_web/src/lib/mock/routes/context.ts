/**
 * In-browser stand-in for the admin API, enabled with `VITE_ADMIN_MOCK=1`
 * (`npm run dev:mock`). Serves the fixtures in fixtures.ts, keeps PUT results
 * in memory for the session, and signs the SPA in with a fake admin ID token so
 * every page renders with data and no AWS stack.
 *
 * Never enable in a production build: `isAdminMockEnabled()` is the only gate.
 */
import type {
  HouseFinanceData,
  FinancePersistedState,
} from "../../financeModel";
import type {
  MirroredBookSummary,
} from "../../mirroredBook";
import {
  MIRRORED_STATEMENT_BOOK_KEYS,
  type StatementBookKey,
} from "../../financeTypes";
import {
  kebabBookKey,
} from "../../statementOwners";
import {
  boardActionsFixture,
  boardApprovalsFixture,
  boardOverviewFixture,
  boardBreakersFixture,
  boardHoldsFixture,
  boardLessonsFixture,
  boardStaffFixture,
  boardTasksFixture,
  boardWatchesFixture,
  boardProspectsFixture,
  boardContentFixture,
  financeFixture,
  evolveSproutsBookFixture,
  evolveSproutsSummaryFixture,
  lxSoftwareBookFixture,
  siuTinDeiBookFixture,
} from "../fixtures";
import {
  DEFAULT_LINKEDIN_SETTINGS,
  SAMPLE_LINKEDIN_IDEAS,
  SAMPLE_LINKEDIN_POSTS,
  type LinkedInConnection,
  type LinkedInIdea,
  type LinkedInPost,
  type LinkedInDraftSettings,
} from "../../linkedinModel";
import {
  DEFAULT_BOARD_BOUNDARIES,
  type BoardAction,
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
  type BoardCatalogJob,
  type BoardSettings,
  type BoardStagingPreview,
} from "../../boardModel";

type MockState = {
  finance: FinancePersistedState;
  books: Record<string, HouseFinanceData>;
  mirrorSummaries: Partial<Record<StatementBookKey, MirroredBookSummary>>;
  seats: BoardSeat[];
  tasks: BoardTask[];
  actions: BoardAction[];
  holds: BoardHold[];
  boundaries: BoardBoundaries;
  lessons: BoardLesson[];
  breakers: BoardBreaker[];
  watches: BoardWatch[];
  prospects: BoardProspect[];
  sequences: Record<string, BoardSequence>;
  content: BoardContentItem[];
  approvals: BoardApproval[];
  settings: BoardSettings;
  staging: BoardStagingPreview;
  catalogJobs: Record<string, BoardCatalogJob>;
  linkedin: {
    settings: LinkedInDraftSettings;
    posts: LinkedInPost[];
    ideas: LinkedInIdea[];
    connection: LinkedInConnection;
    oauthState: string;
  };
};

function initialMockState(): MockState {
  return {
    finance: structuredClone(financeFixture) as FinancePersistedState,
    books: {
      "siu-tin-dei": structuredClone(siuTinDeiBookFixture) as HouseFinanceData,
      "lx-software": structuredClone(lxSoftwareBookFixture) as HouseFinanceData,
      "evolve-sprouts": structuredClone(evolveSproutsBookFixture) as HouseFinanceData,
    },
    mirrorSummaries: {
      evolveSprouts: structuredClone(evolveSproutsSummaryFixture),
    },
    seats: structuredClone(boardStaffFixture.seats) as BoardSeat[],
    tasks: structuredClone(boardTasksFixture),
    actions: structuredClone(boardActionsFixture) as BoardAction[],
    holds: structuredClone(boardHoldsFixture) as BoardHold[],
    boundaries: structuredClone(DEFAULT_BOARD_BOUNDARIES),
    lessons: structuredClone(boardLessonsFixture) as BoardLesson[],
    breakers: structuredClone(boardBreakersFixture) as BoardBreaker[],
    watches: structuredClone(boardWatchesFixture) as BoardWatch[],
    prospects: structuredClone(boardProspectsFixture) as BoardProspect[],
    sequences: {},
    content: structuredClone(boardContentFixture) as BoardContentItem[],
    approvals: structuredClone(boardApprovalsFixture) as BoardApproval[],
    settings: structuredClone(boardOverviewFixture.settings) as BoardSettings,
    staging: {
      status: "diverged",
      behindBy: 3,
      aheadBy: 1,
      canPromote: false,
      commits: [{ sha: "a1b2c3d4", message: "board: #42 add booking" }],
    },
    catalogJobs: {},
    linkedin: {
      settings: structuredClone(DEFAULT_LINKEDIN_SETTINGS),
      posts: structuredClone(SAMPLE_LINKEDIN_POSTS),
      ideas: structuredClone(SAMPLE_LINKEDIN_IDEAS),
      connection: {
        status: "not_connected",
        channel: "profile",
        memberName: "",
        organizationId: "",
        organizationName: "",
        organizations: [],
        tokenExpiresAt: "",
        includeOrganizations: false,
        appConfigured: true,
        appStatus: "ready",
      },
      oauthState: "",
    },
  };
}

export let state: MockState = initialMockState();

export function resetAdminMockState(): void {
  state = initialMockState();
}

export function setMockStaging(preview: BoardStagingPreview): void {
  state.staging = { ...preview };
}

export function mirroredBookFromPath(
  pathname: string,
): { key: StatementBookKey; rest: string } | null {
  const [slug, ...tail] = pathname.split("/").filter(Boolean);
  if (!slug) return null;
  const key = MIRRORED_STATEMENT_BOOK_KEYS.find((book) => kebabBookKey(book) === slug);
  if (!key) return null;
  return { key, rest: tail.join("/") };
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function notFound(path: string): Response {
  return json({ message: `Mock API has no route for ${path}` }, 404);
}

export function parseBody(init: RequestInit): Record<string, unknown> {
  if (typeof init.body !== "string" || !init.body) return {};
  try {
    return JSON.parse(init.body) as Record<string, unknown>;
  } catch {
    return {};
  }
}

export const FINANCE_LIST_KEYS: Readonly<Record<string, keyof FinancePersistedState>> = {
  investments: "investmentRecords",
  savings: "savingsRecords",
  pension: "pensionRecords",
  accounts: "accountRecords",
  liabilities: "liabilityRecords",
  allocations: "allocationRecords",
  income: "incomeRecords",
  expenses: "expenseRecords",
};

export function fxRates(url: URL): Response {
  const base = url.searchParams.get("base") ?? "HKD";
  const quotes = (url.searchParams.get("quotes") ?? "").split(",").filter(Boolean);
  // HKD per 1 unit of each currency. Frankfurter rows mean 1 base = rate quote.
  const inHkd: Record<string, number> = { HKD: 1, USD: 7.8, GBP: 9.9, EUR: 8.5, CNY: 1.08, SGD: 5.8, AED: 2.12 };
  const baseHkd = inHkd[base] ?? 1;
  const date = new Date().toISOString().slice(0, 10);
  return json(
    quotes.map((quote) => ({
      date,
      base,
      quote,
      rate: baseHkd / (inHkd[quote] ?? 1),
    })),
  );
}

export function overlayUsageRange<T extends { from: string; to: string }>(
  url: URL,
  fixture: T,
): T {
  const from = url.searchParams.get("from");
  const to = url.searchParams.get("to");
  if (!from && !to) return fixture;
  return { ...fixture, from: from || fixture.from, to: to || fixture.to };
}

export function quotes(url: URL): Response {
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


export function countsFromTasks(tasks: readonly BoardTask[]): Record<string, number> {
  const counts: Record<string, number> = {
    queued: 0,
    running: 0,
    waiting_approval: 0,
    waiting_subtask: 0,
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
