import type { MockCtx } from "./types";
import { BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD, BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT } from "../../contracts/generated";
import {
  boardMailThreadsFixture,
  boardMeetingsFixture,
  boardOverviewFixture,
  boardProgressFixture,
  boardReceivablesFixture,
  boardReviewFixture,
  boardSequenceFixture,
  boardStaffFixture,
  boardTaskDetailFixture,
  boardTasksFixture,
  boardToolsFixture,
  boardChangesFixture,
  boardOutreachStatsFixture,
} from "../fixtures";
import {
  countsFromTasks,
  json,
  parseBody,
  state,
} from "./context";
import type {
  BoardAction,
  BoardApproval,
  BoardBoundaries,
  BoardContentItem,
  BoardLesson,
  BoardSequence,
  BoardSettings,
  BoardTask,
  BoardWatch,
} from "../../boardModel";

export function handleB0(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === board)) return null;

      return json({
        ...boardOverviewFixture,
        settings: { ...state.settings, boundaries: state.boundaries },
      });
    return null;
}

export function handleB1(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/settings` && method === "PUT")) return null;

      const body = parseBody(init) as Partial<BoardSettings>;
      state.settings = {
        ...state.settings,
        ...body,
        staff: {
          enabled: Boolean(body.staff?.enabled ?? state.settings.staff?.enabled),
          maxRunningTasks:
            body.staff?.maxRunningTasks ??
            state.settings.staff?.maxRunningTasks ??
            BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT,
          dailyBudgetUsd:
            body.staff?.dailyBudgetUsd ??
            state.settings.staff?.dailyBudgetUsd ??
            BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD,
          dutiesEnabled: body.staff?.dutiesEnabled ?? state.settings.staff?.dutiesEnabled,
          seniorPaused: body.staff?.seniorPaused ?? state.settings.staff?.seniorPaused,
          modelBySeat: body.staff?.modelBySeat ?? state.settings.staff?.modelBySeat,
        },
        review: body.review ?? state.settings.review,
        updatedAt: new Date().toISOString(),
      };
      return json({ settings: state.settings });
    return null;
}

export function handleB2(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/actions`)) return null;
  return json({ actions: state.actions });
}

export function handleB3(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/actions/`) && method === "PUT")) return null;

      const actionId = p.slice(`${board}/actions/`.length);
      const idx = state.actions.findIndex((a) => a.actionId === actionId);
      if (idx < 0) return json({ message: "Action not found" }, 404);
      const body = parseBody(init);
      state.actions[idx] = {
        ...state.actions[idx],
        ...(typeof body.status === "string" ? { status: body.status as BoardAction["status"] } : {}),
        ...(typeof body.note === "string" ? { note: body.note } : {}),
        updatedAt: new Date().toISOString(),
      };
      return json({ action: state.actions[idx] });
    return null;
}

export function handleB4(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/approvals`)) return null;
  return json({ approvals: state.approvals });
}

export function handleB5(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/meetings`)) return null;
  return json({ meetings: boardMeetingsFixture });
}

export function handleB6(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/tools`)) return null;
  return json(boardToolsFixture);
}

export function handleB7(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/tools/calls`)) return null;
  return json({ calls: [] });
}

export function handleB8(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/updates`)) return null;
  return json({ updates: [] });
}

export function handleB9(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/receivables`)) return null;
  return json(boardReceivablesFixture);
}

export function handleB10(ctx: MockCtx): Response | null {
  const url = ctx.url;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/mail`)) return null;

      const archived = url.searchParams.get("archived");
      let threads = boardMailThreadsFixture;
      if (archived === "1" || archived === "true") {
        threads = threads.filter((t) => t.disposition === "archived");
      } else {
        threads = threads.filter((t) => t.disposition !== "archived");
      }
      const mailboxes = [
        {
          address: "hello@siutindei.com",
          threadCount: boardMailThreadsFixture.filter((t) => t.disposition !== "archived").length,
          unreadCount: boardMailThreadsFixture.filter((t) => t.unread && t.disposition !== "archived").length,
          lastMessageAt: boardMailThreadsFixture[0]?.lastMessageAt ?? "",
        },
      ];
      return json({
        threads,
        total: threads.length,
        mailboxes,
        status: boardOverviewFixture.mail,
      });
    return null;
}

export function handleB11(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/mail/`) && p !== `${board}/mail/selftest`)) return null;

      const rest = p.slice(`${board}/mail/`.length);
      const [threadId, action] = rest.split("/");
      const thread = boardMailThreadsFixture.find((t) => t.threadId === threadId);
      if (!thread) return json({ message: "Not found" }, 404);
      if (action === "read" && method === "POST") {
        return json({ thread: { ...thread, unread: false } });
      }
      return json({
        thread,
        messages: [
          {
            messageId: `${threadId}-1`,
            threadId,
            direction: thread.lastDirection,
            source: "ses",
            mailbox: thread.mailbox,
            from: { address: thread.lastFrom, name: thread.lastFromName ?? "" },
            to: [thread.mailbox],
            cc: [],
            subject: thread.subject,
            date: thread.lastMessageAt,
            receivedAt: thread.lastMessageAt,
            text: thread.snippet,
            attachments: [],
          },
        ],
      });
    return null;
}

export function handleB12(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/mail/selftest` && method === "POST")) return null;

      return json({
        ok: true,
        to: "mock.admin@example.com",
        from: `hello@${boardOverviewFixture.mail.domain}`,
        sesMessageId: "mock-ses-1",
        health: boardOverviewFixture.mail.sendHealth,
      });
    return null;
}

export function handleB13(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/staff`)) return null;

      return json({
        ...boardStaffFixture,
        seats: state.seats,
        counts: countsFromTasks(state.tasks),
      });
    return null;
}

export function handleB14(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/staff/tick`)) return null;

      if (method !== "POST") return json({ message: "Method not allowed" }, 405);
      return json({ ok: true, queued: true });
    return null;
}

export function handleB15(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/staff/`))) return null;

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
    return null;
}

export function handleB16(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const url = ctx.url;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/tasks`)) return null;

      if (method === "POST") {
        const body = parseBody(init);
        const prNumber = Number(body.prNumber);
        const issueNumber = Number(body.issueNumber);
        const created: BoardTask = {
          ...boardTasksFixture[0],
          taskId: `task-${state.tasks.length + 1}`,
          status: "queued",
          assignee: String(body.assignee || "cfo"),
          assigneeKind: String(body.assignee || "").includes("-") ? "seat" : "persona",
          brief: String(body.brief || "Untitled"),
          deliverableType: (body.deliverableType as BoardTask["deliverableType"]) || "markdown",
          actionId: typeof body.actionId === "string" && body.actionId ? body.actionId : null,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          eventRef:
            Number.isInteger(prNumber) && prNumber > 0
              ? {
                  kind: "code-implement",
                  id: `pr:${prNumber}:owner`,
                  prNumber,
                  ...(Number.isInteger(issueNumber) && issueNumber > 0 ? { issueNumber } : {}),
                }
              : null,
        };
        state.tasks = [created, ...state.tasks];
        if (created.actionId) {
          state.actions = state.actions.map((a) =>
            a.actionId === created.actionId ? { ...a, assignee: created.assignee, staffTaskId: created.taskId } : a,
          );
        }
        return json({ task: created }, 201);
      }
      const status = url.searchParams.get("status");
      const tasks = status ? state.tasks.filter((t) => t.status === status) : state.tasks;
      return json({ tasks, counts: countsFromTasks(state.tasks) });
    return null;
}

export function handleB17(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/tasks/`))) return null;

      const rest = p.slice(`${board}/tasks/`.length).split("/");
      const taskId = rest[0];
      const task = state.tasks.find((t) => t.taskId === taskId);
      if (!task) return json({ message: "Task not found" }, 404);
      if (rest[1] === "cancel" && method === "POST") {
        if (task.status === "cancelled") return json({ task });
        if (task.status === "delivered") return json({ message: "Delivered tasks cannot be cancelled" }, 409);
        const prior = String(task.failureReason || "").trim();
        const fromFailed = task.status === "failed";
        Object.assign(task, {
          status: "cancelled",
          cancelledFrom: fromFailed ? "failed" : undefined,
          failureReason: fromFailed && prior ? `${prior}; cancelled by mock` : `cancelled by mock`,
          updatedAt: new Date().toISOString(),
        });
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
      if (rest[1] === "retry" && method === "POST") {
        if (task.status !== "failed" && task.status !== "needs_owner") {
          return json({ message: "Only failed or needs_owner tasks can be retried" }, 409);
        }
        Object.assign(task, {
          status: "queued",
          step: 0,
          stepsUsed: 0,
          failureReason: "",
          finishedAt: null,
          startedAt: null,
          updatedAt: new Date().toISOString(),
        });
        return json({ task });
      }
      const detail = boardTaskDetailFixture(taskId);
      return json({
        ...(detail ?? { steps: [], reviews: [], deliverable: "", deliverableUrl: "" }),
        task,
      });
    return null;
}

export function handleB18(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/holds`)) return null;

      return json({ holds: state.holds.filter((h) => h.status === "scheduled") });
    return null;
}

export function handleB19(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/holds/veto-class` && method === "POST")) return null;

      const body = parseBody(init);
      const classKey = String(body.classKey || "");
      state.holds = state.holds.map((h) =>
        h.classKey === classKey && h.status === "scheduled" ? { ...h, status: "vetoed" as const } : h,
      );
      return json({ holds: state.holds.filter((h) => h.status === "vetoed" && h.classKey === classKey) });
    return null;
}

export function handleB20(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/holds/`) && p.endsWith("/veto") && method === "POST")) return null;

      const holdId = p.slice(`${board}/holds/`.length, -"/veto".length);
      const idx = state.holds.findIndex((h) => h.holdId === holdId);
      if (idx < 0) return json({ message: "Hold not found" }, 404);
      state.holds[idx] = { ...state.holds[idx], status: "vetoed" };
      return json({ hold: state.holds[idx] });
    return null;
}

export function handleB21(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/boundaries` && method === "PUT")) return null;

      state.boundaries = parseBody(init) as BoardBoundaries;
      return json({ boundaries: state.boundaries });
    return null;
}

export function handleB22(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/ramp`)) return null;

      return json({
        ramp: [{ classKey: "publish:facebook", actions: 32, vetoes: 0, rate: 0, eligibleForPromotion: true, shouldDemote: false }],
      });
    return null;
}

export function handleB23(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/ramp/`) && p.endsWith("/promote") && method === "POST")) return null;

      return json({ classKey: decodeURIComponent(p.slice(`${board}/ramp/`.length, -"/promote".length)), holdOverrides: { "publish:facebook": 0 } });
    return null;
}

export function handleB24(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/code/staging`)) return null;

      return json({ staging: state.staging });
    return null;
}

export function handleB25(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/code/sync-staging` && method === "POST")) return null;

      const before = state.staging;
      if ((before.behindBy ?? 0) <= 0 && before.syncOnly) {
        state.staging = {
          ...before,
          status: "identical",
          behindBy: 0,
          aheadBy: 0,
          canPromote: false,
          syncOnly: false,
          commits: [],
        };
        return json({ ok: true, alreadyCurrent: true, reset: true, preview: state.staging });
      }
      if ((before.behindBy ?? 0) <= 0) {
        return json({ ok: true, alreadyCurrent: true, preview: before });
      }
      state.staging = {
        ...before,
        status: "ahead",
        behindBy: 0,
        aheadBy: before.aheadBy ?? 1,
        canPromote: (before.aheadBy ?? 1) > 0,
      };
      return json({
        ok: true,
        mergedSha: "abcmerged000",
        before,
        preview: state.staging,
      });
    return null;
}

export function handleB26(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/catalog/preview` && method === "POST")) return null;

      const body = parseBody(init);
      const taskId = String(body.taskId || "");
      const task = state.tasks.find((t) => t.taskId === taskId);
      if (!task) return json({ message: "Task not found" }, 404);
      const wantsRemote = body.remote !== false;
      const fallbackDryRun = { ok: true, mode: "local", accepted: 1, skipped: 0, errors: [] };
      const preview = {
        ...(task.importPreview ?? {
          ok: true,
          district: task.eventRef?.district || "Eastern",
          importEnabled: false,
          configured: false,
          dryRun: fallbackDryRun,
          payload: { organizations: [{ name: "Quarry Bay Park Playground", category_name: "Outdoor activity", area_name: "Eastern" }] },
        }),
        taskId,
        dryRun: {
          ...(task.importPreview?.dryRun ?? fallbackDryRun),
          mode: wantsRemote ? "remote" : "local",
        },
      };
      const idx = state.tasks.findIndex((t) => t.taskId === taskId);
      if (idx >= 0) state.tasks[idx] = { ...state.tasks[idx], importPreview: preview };
      return json({ preview });
    return null;
}

export function handleB27(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/catalog/import` && method === "POST")) return null;

      return json({ message: "catalog import is switched off (SiutindeiBoardCatalogImportEnabled)" }, 409);
    return null;
}

export function handleB28(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/catalog/skip` && method === "POST")) return null;

      const body = parseBody(init);
      const taskId = String(body.taskId || "");
      const idx = state.tasks.findIndex((t) => t.taskId === taskId);
      if (idx < 0) return json({ message: "Task not found" }, 404);
      const now = new Date().toISOString();
      state.tasks[idx] = {
        ...state.tasks[idx],
        status: "delivered",
        importSkipped: true,
        importPhase: "skipped",
        finishedAt: now,
      };
      return json({ ok: true, skipped: true, task: state.tasks[idx] });
    return null;
}

export function handleB29(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/catalog/requeue` && method === "POST")) return null;

      const body = parseBody(init);
      const taskId = String(body.taskId || "");
      const idx = state.tasks.findIndex((t) => t.taskId === taskId);
      if (idx < 0) return json({ message: "Task not found" }, 404);
      state.tasks[idx] = {
        ...state.tasks[idx],
        status: "awaiting_import",
        importPhase: "pending",
        importError: "",
        finishedAt: null,
      };
      return json({ ok: true, task: state.tasks[idx], taskId });
    return null;
}

export function handleB30(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/catalog/reimport` && method === "POST")) return null;

      const body = parseBody(init);
      const taskId = String(body.taskId || "");
      const idx = state.tasks.findIndex((t) => t.taskId === taskId);
      if (idx < 0) return json({ message: "Task not found" }, 404);
      return json({ ok: true, taskId, reimported: true });
    return null;
}

export function handleB31(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/catalog/sources` && method === "GET")) return null;

      return json({
        launchTarget: 1000,
        candidateCounts: { lcsd: { new: 0, approved: 2, imported: 0, rejected: 0, closed: 0 } },
        sources: [
          {
            id: "lcsd",
            counts: { new: 0, approved: 2, imported: 0, rejected: 0, closed: 0 },
            available: 2,
            lastImport: null,
            lastPreview: null,
            job: state.catalogJobs.lcsd ?? null,
          },
          {
            id: "swd",
            counts: { new: 0, approved: 3, imported: 0, rejected: 0, closed: 0 },
            available: 3,
            lastImport: null,
            lastPreview: null,
            job: state.catalogJobs.swd ?? {
              phase: "running",
              action: "ingest",
              offset: 500,
              remaining: 200,
            },
          },
        ],
      });
    return null;
}

export function handleB32(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/catalog/bulk/`) && p.endsWith("/preview") && method === "POST")) return null;

      const source = p.split("/")[5] || "lcsd";
      state.catalogJobs[source] = { phase: "queued", action: "preview" };
      return json({ ok: true, queued: true, invoked: true, source, action: "preview" });
    return null;
}

export function handleB33(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/catalog/bulk/`) && p.endsWith("/import") && method === "POST")) return null;

      const source = p.split("/")[5] || "lcsd";
      state.catalogJobs[source] = { phase: "queued", action: "import" };
      return json({ ok: true, queued: true, invoked: true, source, action: "import" });
    return null;
}

export function handleB34(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const url = ctx.url;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/catalog/candidates` && method === "GET")) return null;

      const all = [
        {
          candidateId: "cand-1",
          source: "competitor",
          nameEn: "Example Playhouse",
          district: "Sha Tin",
          status: "new",
        },
      ];
      const source = url.searchParams.get("source");
      const district = url.searchParams.get("district");
      const q = (url.searchParams.get("q") || "").toLowerCase();
      const status = url.searchParams.get("status");
      const missingPlaceId = url.searchParams.get("missingPlaceId") === "true";
      const filtered = all.filter((row) => {
        if (status && row.status !== status) return false;
        if (source && row.source !== source) return false;
        if (district && row.district !== district) return false;
        if (q && !`${row.nameEn} ${row.district} ${row.source}`.toLowerCase().includes(q)) return false;
        if (missingPlaceId && "placeId" in row && row.placeId) return false;
        return true;
      });
      const cursor = Number(url.searchParams.get("cursor") || 0) || 0;
      const limit = Number(url.searchParams.get("limit") || 20) || 20;
      const page = filtered.slice(cursor, cursor + limit);
      return json({
        candidates: page,
        nextCursor: cursor + limit < filtered.length ? cursor + limit : null,
        total: filtered.length,
      });
    return null;
}

export function handleB35(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/catalog/candidates/bulk` && method === "POST")) return null;

      const body = parseBody(init);
      const status =
        body.decision === "approve" ? "approved" : body.decision === "close" ? "closed" : "rejected";
      return json({ updated: body.decision === "approve" ? 0 : 1, status });
    return null;
}

export function handleB36(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/catalog/discovery/run` && method === "POST")) return null;

      return json({ ok: true, queued: true, invoked: true });
    return null;
}

export function handleB37(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/code/promote` && method === "POST")) return null;

      const now = new Date().toISOString();
      const approval: BoardApproval = {
        approvalId: `appr-promote-${state.approvals.length + 1}`,
        status: "pending",
        personaId: "cto",
        displayName: "CTO",
        toolId: "code",
        toolLabel: "Code",
        op: "code_promote",
        kind: "write",
        arguments: { kind: "production" },
        summary: "Open a staging→main PR for board: #42 add booking",
        reason: "code_promote always queues an Approval",
        context: { kind: "review" },
        createdAt: now,
        updatedAt: now,
      };
      state.approvals = [approval, ...state.approvals];
      return json(
        {
          approval,
          preview: { status: "ahead", aheadBy: 1, behindBy: 0, canPromote: true, commits: [] },
        },
        201,
      );
    return null;
}

export function handleB38(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/review`)) return null;

      return json({ review: boardReviewFixture });
    return null;
}

export function handleB39(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/progress`)) return null;

      return json(boardProgressFixture);
    return null;
}

export function handleB40(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/review/sample/`) && p.endsWith("/wrong") && method === "POST")) return null;

      const callId = decodeURIComponent(p.slice(`${board}/review/sample/`.length, -"/wrong".length));
      const lesson: BoardLesson = {
        lessonId: `lsn-${state.lessons.length + 1}`,
        kind: "correction",
        subject: "cmo",
        classKey: "publish:facebook",
        what: callId,
        instruction: "Do not repeat this post without a district and a date.",
        confirmed: false,
        createdAt: new Date().toISOString(),
      };
      state.lessons = [lesson, ...state.lessons];
      return json({ lesson });
    return null;
}

export function handleB41(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/lessons`)) return null;

      return json({ lessons: state.lessons });
    return null;
}

export function handleB42(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/lessons/`) && p.endsWith("/confirm") && method === "POST")) return null;

      const lessonId = decodeURIComponent(p.slice(`${board}/lessons/`.length, -"/confirm".length));
      const body = parseBody(init) as { instruction?: string };
      state.lessons = state.lessons.map((l) =>
        l.lessonId === lessonId ? { ...l, confirmed: true, instruction: body.instruction || l.instruction } : l,
      );
      return json({ lesson: state.lessons.find((l) => l.lessonId === lessonId) });
    return null;
}

export function handleB43(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/lessons/`) && p.endsWith("/dismiss") && method === "POST")) return null;

      const lessonId = decodeURIComponent(p.slice(`${board}/lessons/`.length, -"/dismiss".length));
      state.lessons = state.lessons.map((l) => (l.lessonId === lessonId ? { ...l, dismissed: true } : l));
      return json({ lesson: state.lessons.find((l) => l.lessonId === lessonId) });
    return null;
}

export function handleB44(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/breakers`)) return null;

      return json({ breakers: state.breakers });
    return null;
}

export function handleB45(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/breakers/`) && p.endsWith("/reset") && method === "POST")) return null;

      const name = decodeURIComponent(p.slice(`${board}/breakers/`.length, -"/reset".length));
      state.breakers = state.breakers.map((b) => (b.name === name ? { ...b, tripped: false, resetAt: new Date().toISOString() } : b));
      return json({ breaker: state.breakers.find((b) => b.name === name) });
    return null;
}

export function handleB46(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/watchlist`)) return null;

      if (method === "POST") {
        const body = parseBody(init);
        const watch: BoardWatch = {
          watchId: `watch-${state.watches.length + 1}`,
          name: String(body.name ?? ""),
          kind: String(body.kind ?? "competitor"),
          urls: Array.isArray(body.urls) ? body.urls.map(String) : [],
          ...(typeof body.district === "string" && body.district.trim() ? { district: body.district.trim() } : {}),
          appIds: typeof body.appIds === "object" && body.appIds ? (body.appIds as Record<string, string>) : {},
          createdAt: new Date().toISOString(),
        };
        state.watches = [watch, ...state.watches];
        return json({ watch }, 201);
      }
      return json({
        watches: state.watches,
        latestBrief: { taskId: "task-review", status: "review", summary: "Weekly market brief" },
      });
    return null;
}

export function handleB47(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/watchlist/`))) return null;

      const watchId = decodeURIComponent(p.slice(`${board}/watchlist/`.length));
      const idx = state.watches.findIndex((w) => w.watchId === watchId);
      if (idx < 0) return json({ message: "Watch not found" }, 404);
      if (method === "DELETE") {
        state.watches = state.watches.filter((w) => w.watchId !== watchId);
        return json({ ok: true });
      }
      if (method === "PUT") {
        const body = parseBody(init);
        const next = {
          ...state.watches[idx],
          ...(typeof body.name === "string" ? { name: body.name } : {}),
          ...(typeof body.kind === "string" ? { kind: body.kind } : {}),
          ...(Array.isArray(body.urls) ? { urls: body.urls.map(String) } : {}),
        };
        if (typeof body.district === "string") {
          if (body.district.trim()) next.district = body.district.trim();
          else delete next.district;
        }
        state.watches[idx] = next;
        return json({ watch: state.watches[idx] });
      }
    return null;
}

export function handleB48(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/changes`)) return null;

      return json({ changes: boardChangesFixture });
    return null;
}

export function handleB49(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/prospects`)) return null;

      return json({
        prospects: state.prospects,
        needsContact: state.prospects.filter((row) => row.stage === "qualified" && !row.contact),
        stats: boardOutreachStatsFixture,
      });
    return null;
}

export function handleB50(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/prospects/import` && method === "POST")) return null;

      const body = parseBody(init);
      const lines = String(body.csv ?? "").trim().split("\n").slice(1);
      let created = 0;
      for (const line of lines) {
        const [name, type, district, website, email] = line.split(",");
        if (!name) continue;
        state.prospects = [
          {
            prospectId: `pros-${state.prospects.length + 1}`,
            name,
            type: type || "provider",
            district,
            website,
            email,
            contact: email || null,
            stage: "discovered",
            source: "owner",
          },
          ...state.prospects,
        ];
        created += 1;
      }
      return json({ created, updated: 0, errors: [] });
    return null;
}

export function handleB51(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/prospects/`) && p.endsWith("/merge") && method === "POST")) return null;

      const prospectId = decodeURIComponent(p.slice(`${board}/prospects/`.length, -"/merge".length));
      const body = parseBody(init);
      const into = String(body.into ?? "");
      const src = state.prospects.find((row) => row.prospectId === prospectId);
      const destIdx = state.prospects.findIndex((row) => row.prospectId === into);
      if (!src || destIdx < 0) return json({ message: "Prospect not found" }, 404);
      state.prospects[destIdx] = { ...state.prospects[destIdx], name: state.prospects[destIdx].name || src.name };
      state.prospects = state.prospects.map((row) => (row.prospectId === prospectId ? { ...row, stage: "suppressed" } : row));
      return json({ prospect: state.prospects[destIdx] });
    return null;
}

export function handleB52(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/prospects/`))) return null;

      const prospectId = decodeURIComponent(p.slice(`${board}/prospects/`.length));
      const idx = state.prospects.findIndex((row) => row.prospectId === prospectId);
      if (idx < 0) return json({ message: "Prospect not found" }, 404);
      if (method === "PUT") {
        const body = parseBody(init);
        state.prospects[idx] = {
          ...state.prospects[idx],
          ...(typeof body.stage === "string" ? { stage: body.stage } : {}),
          ...(typeof body.contact === "string" ? { contact: body.contact } : {}),
          ...(typeof body.type === "string" ? { type: body.type } : {}),
          ...(typeof body.note === "string" ? { ownerNote: body.note } : {}),
        };
      }
      return json({ prospect: state.prospects[idx] });
    return null;
}

export function handleB53(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/outreach/stats`)) return null;

      return json(boardOutreachStatsFixture);
    return null;
}

export function handleB54(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/sequences/`))) return null;

      const type = decodeURIComponent(p.slice(`${board}/sequences/`.length));
      if (method === "PUT") {
        const body = parseBody(init);
        state.sequences[type] = { type, steps: Array.isArray(body.steps) ? body.steps : [] } as BoardSequence;
        return json({ sequence: state.sequences[type] });
      }
      return json({ sequence: state.sequences[type] ?? boardSequenceFixture(type) });
    return null;
}

export function handleB55(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p === `${board}/content`)) return null;

      if (method === "POST") {
        const body = parseBody(init);
        const item: BoardContentItem = {
          contentId: `cnt-${state.content.length + 1}`,
          status: "drafted",
          channel: String(body.channel || "facebook"),
          pillar: String(body.pillar || "activity spotlight"),
          slotAt: String(body.slotAt || new Date().toISOString()),
          copyEn: String(body.copyEn || ""),
          copyZh: String(body.copyZh || ""),
        };
        state.content = [item, ...state.content];
        return json({ item });
      }
      return json({
        items: state.content,
        assisted: state.content.filter((row) => String(row.channel || "").startsWith("assisted")),
      });
    return null;
}

export function handleB56(ctx: MockCtx): Response | null {
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p.includes("/creative/") && p.startsWith(`${board}/content/`))) return null;

      return json({ url: "https://assets.example/board/content/preview.png", key: "preview.png" });
    return null;
}

export function handleB57(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/content/`) && p.endsWith("/render") && method === "POST")) return null;

      const contentId = decodeURIComponent(p.slice(`${board}/content/`.length, -"/render".length));
      const item = state.content.find((row) => row.contentId === contentId);
      if (!item) return json({ message: "Not found" }, 404);
      return json({ item });
    return null;
}

export function handleB58(ctx: MockCtx): Response | null {
  const method = ctx.method;
  const p = ctx.path;
  const init = ctx.init;
  const board = "/siu-tin-dei/board";
  if (!(p.startsWith(`${board}/content/`))) return null;

      const contentId = decodeURIComponent(p.slice(`${board}/content/`.length));
      const idx = state.content.findIndex((row) => row.contentId === contentId);
      if (idx < 0) return json({ message: "Not found" }, 404);
      if (method === "PUT") {
        const body = parseBody(init);
        state.content[idx] = { ...state.content[idx], ...body } as BoardContentItem;
      }
      return json({ item: state.content[idx] });
    return null;
}
