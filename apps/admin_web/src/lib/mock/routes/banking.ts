import type { MockCtx } from "./types";
import { bankingFixture } from "../fixtures";
import { json, parseBody } from "./context";

export function handleB0(ctx: MockCtx): Response | null {
  const p = ctx.path;
  if (!(p === "/banking")) return null;
  return json(bankingFixture);
}

export function handleB1(ctx: MockCtx): Response | null {
  const p = ctx.path;
  if (!(p === "/banking/banks")) return null;

      return json({
        banks: [
          { name: "Monzo", country: "GB", beta: false, maximumConsentValidity: 90 * 86_400 },
          { name: "Barclays", country: "GB", beta: false, maximumConsentValidity: 90 * 86_400 },
        ],
      });
    return null;
}

export function handleB2(ctx: MockCtx): Response | null {
  const p = ctx.path;
  if (!(p === "/banking/sync")) return null;
  return json(bankingFixture.lastSync);
}

export function handleB3(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const init = ctx.init;
  if (!(p === "/banking/mappings")) return null;
  return json({ mappings: parseBody(init).mappings ?? bankingFixture.mappings });
}
