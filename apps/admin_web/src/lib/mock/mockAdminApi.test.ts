import { describe, expect, it } from "vitest";
import { mockAdminFetch } from "./mockAdminApi";

describe("mockAdminFetch", () => {
  it("serves finance accounts used by the Accounts tab", async () => {
    const res = await mockAdminFetch("/finance");
    expect(res.ok).toBe(true);
    const body = (await res.json()) as { accountRecords: readonly { id: string }[] };
    expect(body.accountRecords.map((r) => r.id)).toContain("ac-1");
  });

  it("serves the Siu Tin Dei book and board overview", async () => {
    const book = await mockAdminFetch("/siu-tin-dei");
    expect(book.ok).toBe(true);
    const board = await mockAdminFetch("/siu-tin-dei/board");
    const overview = (await board.json()) as { openActionCount: number };
    expect(overview.openActionCount).toBeGreaterThan(0);
  });

  it("serves the OpenRouter usage split for the dashboard", async () => {
    const res = await mockAdminFetch("/openrouter/usage");
    expect(res.ok).toBe(true);
    const body = (await res.json()) as {
      costCenters: readonly { id: string; cost: number }[];
    };
    expect(body.costCenters.map((c) => c.id)).toContain("siuTinDei");
  });

  it("returns 404 for unknown paths", async () => {
    const res = await mockAdminFetch("/no-such-route");
    expect(res.status).toBe(404);
  });
});
