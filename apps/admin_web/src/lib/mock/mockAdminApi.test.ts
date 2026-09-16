import { describe, expect, it } from "vitest";
import { mockAdminFetch } from "./mockAdminApi";

describe("mockAdminFetch", () => {
  it("serves finance accounts used by the Accounts tab", async () => {
    const res = await mockAdminFetch("/finance");
    expect(res.ok).toBe(true);
    const body = (await res.json()) as { accountRecords: readonly { id: string }[] };
    expect(body.accountRecords.map((r) => r.id)).toContain("ac-1");
  });

  it("serves listing and partnership progress", async () => {
    const res = await mockAdminFetch("/siu-tin-dei/board/progress");
    expect(res.ok).toBe(true);
    const body = (await res.json()) as { listings: { activities: number }; bottlenecks: unknown[] };
    expect(body.listings.activities).toBe(12);
    expect(body.bottlenecks.length).toBeGreaterThan(0);
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

  it("starts staging behind main and Sync from main makes it promotable", async () => {
    const beforeRes = await mockAdminFetch("/siu-tin-dei/board/code/staging");
    expect(beforeRes.ok).toBe(true);
    const before = (await beforeRes.json()) as {
      staging: { behindBy?: number; canPromote?: boolean; commits?: readonly { message?: string }[] };
    };
    expect(before.staging.commits?.[0]?.message).toMatch(/board: #42 add booking/);
    if ((before.staging.behindBy ?? 0) > 0) {
      expect(before.staging.canPromote).toBe(false);
    }

    const syncRes = await mockAdminFetch("/siu-tin-dei/board/code/sync-staging", { method: "POST" });
    expect(syncRes.ok).toBe(true);
    const synced = (await syncRes.json()) as {
      ok?: boolean;
      alreadyCurrent?: boolean;
      preview?: { behindBy?: number; canPromote?: boolean };
    };
    expect(synced.ok).toBe(true);
    expect(synced.preview?.behindBy).toBe(0);
    expect(synced.preview?.canPromote).toBe(true);

    const afterRes = await mockAdminFetch("/siu-tin-dei/board/code/staging");
    const after = (await afterRes.json()) as {
      staging: { behindBy?: number; canPromote?: boolean; commits?: readonly { message?: string }[] };
    };
    expect(after.staging.behindBy).toBe(0);
    expect(after.staging.canPromote).toBe(true);
    expect(after.staging.commits?.[0]?.message).toMatch(/board: #42 add booking/);

    const againRes = await mockAdminFetch("/siu-tin-dei/board/code/sync-staging", { method: "POST" });
    const again = (await againRes.json()) as { alreadyCurrent?: boolean };
    expect(again.alreadyCurrent).toBe(true);
  });

  it("returns 404 for unknown paths", async () => {
    const res = await mockAdminFetch("/no-such-route");
    expect(res.status).toBe(404);
  });

  it("persists staff.maxRunningTasks on PUT /siu-tin-dei/board/settings", async () => {
    const put = await mockAdminFetch("/siu-tin-dei/board/settings", {
      method: "PUT",
      body: JSON.stringify({ staff: { enabled: true, maxRunningTasks: 8, dailyBudgetUsd: 20 } }),
    });
    expect(put.ok).toBe(true);
    const saved = (await put.json()) as { settings: { staff: { maxRunningTasks: number } } };
    expect(saved.settings.staff.maxRunningTasks).toBe(8);
    const get = await mockAdminFetch("/siu-tin-dei/board");
    const overview = (await get.json()) as { settings: { staff: { maxRunningTasks: number } } };
    expect(overview.settings.staff.maxRunningTasks).toBe(8);
  });

  it("persists staff.modelBySeat on PUT /siu-tin-dei/board/settings", async () => {
    const put = await mockAdminFetch("/siu-tin-dei/board/settings", {
      method: "PUT",
      body: JSON.stringify({
        staff: { enabled: true, maxRunningTasks: 6, dailyBudgetUsd: 20, modelBySeat: { "engineer-1": "qwen/qwen-2.5-72b-instruct" } },
      }),
    });
    const saved = (await put.json()) as { settings: { staff: { modelBySeat?: Record<string, string> } } };
    expect(saved.settings.staff.modelBySeat?.["engineer-1"]).toBe("qwen/qwen-2.5-72b-instruct");
  });

  it("posts New task prNumber as a revision eventRef and omits it when empty", async () => {
    const withPr = await mockAdminFetch("/siu-tin-dei/board/tasks", {
      method: "POST",
      body: JSON.stringify({
        assignee: "engineer-1",
        brief: "Fix the two failing resolver tests on PR #501.",
        deliverableType: "pr",
        slaHours: 24,
        prNumber: 501,
        issueNumber: 489,
      }),
    });
    expect(withPr.status).toBe(201);
    const created = (await withPr.json()) as {
      task: { eventRef?: { kind?: string; prNumber?: number; issueNumber?: number } | null };
    };
    expect(created.task.eventRef).toEqual(
      expect.objectContaining({ kind: "code-implement", prNumber: 501, issueNumber: 489 }),
    );

    const withoutPr = await mockAdminFetch("/siu-tin-dei/board/tasks", {
      method: "POST",
      body: JSON.stringify({
        assignee: "support",
        brief: "Write a weekly note",
        deliverableType: "markdown",
        slaHours: 24,
      }),
    });
    expect(withoutPr.status).toBe(201);
    const plain = (await withoutPr.json()) as { task: { eventRef?: unknown } };
    expect(plain.task.eventRef).toBeNull();
  });
});
