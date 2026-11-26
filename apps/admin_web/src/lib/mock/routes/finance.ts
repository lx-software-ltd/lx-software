import type { MockCtx } from "./types";
import {
  FINANCE_LIST_KEYS,
  fxRates,
  json,
  mirroredBookFromPath,
  parseBody,
  quotes,
  state,
} from "./context";
import type { FinancePersistedState, HouseFinanceData } from "../../financeModel";
import type { MirroredBookSummary } from "../../mirroredBook";
import { STATEMENT_BOOK_LABELS } from "../../financeTypes";

export function handleF0(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  if (!(p === "/v1/admin/finance" && method === "GET")) return null;
  return json(state.finance);
}

export function handleF1(ctx: MockCtx): Response | null {
  const url = ctx.url;
  const p = ctx.path;
  if (!(p === "/v1/admin/finance/quotes")) return null;
  return quotes(url);
}

export function handleF2(ctx: MockCtx): Response | null {
  const url = ctx.url;
  const p = ctx.path;
  if (!(p === "/v1/admin/fx/rates")) return null;
  return fxRates(url);
}

export function handleF3(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  if (!(p === "/v1/admin/finance/hillmarton" || p === "/v1/admin/finance/morrison")) return null;

      const house = p.slice("/v1/admin/finance/".length) as "hillmarton" | "morrison";
      if (method === "PUT") {
        const data = parseBody(init) as unknown as HouseFinanceData;
        state.finance = { ...state.finance, [house]: data };
      }
      return json({ data: state.finance[house] });
    return null;
}

export function handleF4(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  if (!(p.startsWith("/v1/admin/finance/"))) return null;

      const listKey = FINANCE_LIST_KEYS[p.slice("/v1/admin/finance/".length)];
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
    return null;
}

export function handleF5(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const mirrored = mirroredBookFromPath(p);
  if (!(mirrored && mirrored.rest === "summary" && method === "GET")) return null;

      return json(
        state.mirrorSummaries[mirrored.key] ?? {
          configured: false,
          syncedAt: null,
          lastAttemptAt: null,
          pendingSince: null,
          syncError: null,
          outstandingByCurrency: {},
          openInvoices: 0,
          submittedExpenses: 0,
          paidExpenses: 0,
          skippedUnsupportedCurrency: 0,
          skippedIncomplete: 0,
        },
      );
    return null;
}

export function handleF6(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const mirrored = mirroredBookFromPath(p);
  if (!(mirrored && mirrored.rest === "sync" && method === "POST")) return null;

      const current = state.mirrorSummaries[mirrored.key];
      const now = new Date().toISOString();
      const next: MirroredBookSummary = {
        configured: current?.configured ?? true,
        syncedAt: now,
        lastAttemptAt: now,
        pendingSince: null,
        syncError: null,
        outstandingByCurrency: { ...(current?.outstandingByCurrency ?? {}) },
        openInvoices: current?.openInvoices ?? 0,
        submittedExpenses: current?.submittedExpenses ?? 0,
        paidExpenses: current?.paidExpenses ?? 0,
        skippedUnsupportedCurrency: current?.skippedUnsupportedCurrency ?? 0,
        skippedIncomplete: current?.skippedIncomplete ?? 0,
      };
      state.mirrorSummaries[mirrored.key] = next;
      return json(next);
    return null;
}

export function handleF7(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const mirrored = mirroredBookFromPath(p);
  if (!(
    mirrored &&
    (method === "PUT" || (method === "POST" && mirrored.rest === "parse-statement"))
  )) return null;

      return json(
        {
          message: `${STATEMENT_BOOK_LABELS[mirrored.key]} records come from the product database and cannot be edited here.`,
        },
        403,
      );
    return null;
}

export function handleF8(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const slug = p.startsWith("/v1/admin/") ? p.slice("/v1/admin/".length) : p.slice(1);
  const book = state.books[slug];
  if (!(book)) return null;

      if (method === "PUT") {
        state.books[slug] = parseBody(init) as unknown as HouseFinanceData;
      }
      return json({ data: state.books[slug] });
    return null;
}
