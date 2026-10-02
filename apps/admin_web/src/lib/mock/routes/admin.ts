import type { MockCtx } from "./types";
import {
  assetsFixture,
  awsUsageFixture,
  openrouterUsageFixture,
} from "../fixtures";
import { json, overlayUsageRange } from "./context";

export function handleA0(ctx: MockCtx): Response | null {
  const p = ctx.path;
  if (!(p === "/health")) return null;
  return json({ status: "ok" });
}

export function handleA1(ctx: MockCtx): Response | null {
  const p = ctx.path;
  if (!(p === "/me")) return null;
  return json({ sub: "mock-admin", email: "mock.admin@example.com" });
}

export function handleA2(ctx: MockCtx): Response | null {
  const url = ctx.url;
  const p = ctx.path;
  if (!(p === "/openrouter/usage")) return null;
  return json(overlayUsageRange(url, openrouterUsageFixture));
}

export function handleA3(ctx: MockCtx): Response | null {
  const url = ctx.url;
  const p = ctx.path;
  if (!(p === "/aws/usage")) return null;
  return json(overlayUsageRange(url, awsUsageFixture));
}

export function handleA4(ctx: MockCtx): Response | null {
  const p = ctx.path;
  if (!(p === "/aws/usage.pdf")) return null;

      const body =
        "%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\nlx-software-aws-mock\n";
      return new Response(body, {
        status: 200,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition": 'attachment; filename="lx-software-aws-2026-08.pdf"',
        },
      });
    return null;
}

export function handleA5(ctx: MockCtx): Response | null {
  const p = ctx.path;
  if (!(p === "/records")) return null;
  return json({ items: assetsFixture, nextCursor: null });
}

export function handleA6(ctx: MockCtx): Response | null {
  const p = ctx.path;
  if (!(p === "/assets")) return null;
  return json({ items: assetsFixture, nextCursor: null });
}

export function handleA7(ctx: MockCtx): Response | null {
  const p = ctx.path;
  if (!(p === "/assets/download-url")) return null;
  return json({ url: "about:blank" });
}

export function handleA8(ctx: MockCtx): Response | null {
  const p = ctx.path;
  if (!(p === "/assets/delete")) return null;
  return json({ ok: true });
}

export function handleA9(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  if (!(p.endsWith("/approve") && p.includes("/catalog/candidates/") && method === "POST")) return null;

      return json({ candidate: { candidateId: "cand-1", source: "competitor", nameEn: "Example Playhouse", district: "Sha Tin", status: "approved" } });
    return null;
}

export function handleA10(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  if (!(p.endsWith("/reject") && p.includes("/catalog/candidates/") && method === "POST")) return null;

      return json({ candidate: { candidateId: "cand-1", source: "competitor", nameEn: "Example Playhouse", district: "Sha Tin", status: "rejected" } });
    return null;
}
