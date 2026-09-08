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

  it("serves the OpenRouter usage split for the LX Software dashboard", async () => {
    const res = await mockAdminFetch("/openrouter/usage");
    expect(res.ok).toBe(true);
    const body = (await res.json()) as {
      payer: { id: string };
      apps: readonly { id: string; cost: number }[];
    };
    expect(body.payer.id).toBe("lxSoftware");
    expect(body.apps.map((app) => app.id)).toEqual(
      expect.arrayContaining(["statement-parser", "executive-board", "evolvesprouts", "siutindei"]),
    );
  });

  it("returns 404 for unknown paths", async () => {
    const res = await mockAdminFetch("/no-such-route");
    expect(res.status).toBe(404);
  });
});
