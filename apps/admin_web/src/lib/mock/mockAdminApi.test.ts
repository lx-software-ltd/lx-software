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
    const res = await mockAdminFetch("/openrouter/usage?from=2026-07-01&to=2026-07-31");
    expect(res.ok).toBe(true);
    const body = (await res.json()) as {
      from: string;
      to: string;
      payer: { id: string };
      apps: readonly { id: string; cost: number }[];
    };
    expect(body.from).toBe("2026-07-01");
    expect(body.to).toBe("2026-07-31");
    expect(body.payer.id).toBe("lxSoftware");
    expect(body.apps.map((app) => app.id)).toEqual(
      expect.arrayContaining(["statement-parser", "executive-board", "evolvesprouts", "siutindei"]),
    );
  });

  it("serves the AWS cost split for the LX Software dashboard", async () => {
    const res = await mockAdminFetch("/aws/usage?from=2026-07-01&to=2026-07-31");
    expect(res.ok).toBe(true);
    const body = (await res.json()) as {
      from: string;
      to: string;
      payer: { id: string };
      companies: readonly { id: string; usd: number }[];
    };
    expect(body.from).toBe("2026-07-01");
    expect(body.to).toBe("2026-07-31");
    expect(body.payer.id).toBe("lxSoftware");
    expect(body.companies.map((row) => row.id)).toEqual(
      expect.arrayContaining(["siuTinDei", "evolveSprouts", "lxSoftware"]),
    );
    const pdf = await mockAdminFetch("/aws/usage.pdf");
    expect(pdf.ok).toBe(true);
    expect(pdf.headers.get("Content-Type")).toBe("application/pdf");
  });

  it("returns 404 for unknown paths", async () => {
    const res = await mockAdminFetch("/no-such-route");
    expect(res.status).toBe(404);
  });
});
