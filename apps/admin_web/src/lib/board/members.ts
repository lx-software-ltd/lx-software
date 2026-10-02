import {
  BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD,
  BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT,
} from "../contracts/generated";
import type {
  BoardAction,
  BoardCharterField,
  BoardDmarcSettings,
  BoardMember,
  BoardMemberOverride,
  BoardSeat,
  BoardSettings,
} from "./types";


/** Matches `normalize_staff_config` in `board_store.py`. */
export function staffDraft(
  current: BoardSettings,
  patch: Partial<NonNullable<BoardSettings["staff"]>>,
): NonNullable<BoardSettings["staff"]> {
  return {
    enabled: Boolean(current.staff?.enabled),
    maxRunningTasks: current.staff?.maxRunningTasks ?? BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT,
    dailyBudgetUsd: current.staff?.dailyBudgetUsd ?? BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD,
    dutiesEnabled: current.staff?.dutiesEnabled,
    seniorPaused: current.staff?.seniorPaused,
    disabledReason: current.staff?.disabledReason,
    modelBySeat: current.staff?.modelBySeat,
    ...patch,
  };
}


export function dmarcDraft(
  current: BoardSettings,
  patch: Partial<BoardDmarcSettings>,
): BoardDmarcSettings {
  const base = current.dmarc;
  const policy = { ...base?.expectedPolicy, ...patch.expectedPolicy };
  return {
    enabled: base?.enabled !== false,
    knownSenderDomains: [...(base?.knownSenderDomains ?? [])],
    spoofAlertCount: base?.spoofAlertCount ?? 20,
    silenceDays: base?.silenceDays ?? 3,
    ...patch,
    expectedPolicy: {
      p: policy.p || "quarantine",
      pct: policy.pct ?? 100,
      sp: policy.sp ?? "",
    },
  };
}


export function catalogDraft(
  current: BoardSettings,
  patch: Partial<NonNullable<BoardSettings["catalog"]>>,
): NonNullable<BoardSettings["catalog"]> {
  return {
    autoImport: Boolean(current.catalog?.autoImport),
    microBatchEnabled: current.catalog?.microBatchEnabled !== false,
    launchListingTarget: current.catalog?.launchListingTarget,
    ...patch,
  };
}


/** Display name for an action's assignee: a staff seat first, then a board member. */
export function actionAssigneeLabel(members: readonly BoardMember[], seats: readonly BoardSeat[], assignee: string): string {
  const seat = seats.find((s) => s.id === assignee);
  if (seat) return seat.displayName;
  return memberLabel(members, assignee);
}


/** Brief for a staff task that takes over a founder action. */
export function actionTaskBrief(action: Pick<BoardAction, "title" | "detail" | "metric">): string {
  const parts = [action.title.trim()];
  if (action.detail.trim()) parts.push(`Done looks like: ${action.detail.trim()}`);
  if (action.metric.trim()) parts.push(`Success metric: ${action.metric.trim()}`);
  return parts.join("\n");
}


/** Merge contract defaults with an owner override into the effective profile (mirrors the Lambda). */
export function mergeMemberProfile(
  base: Pick<BoardMember, "id" | "title" | "shortName" | "focusAreas" | "kpisOwned"> &
    Readonly<Record<BoardCharterField, string>>,
  override: BoardMemberOverride | null | undefined,
): Omit<BoardMember, "profileHash"> {
  const ov = override ?? {};
  const isOverridden = {
    vision: Boolean(ov.vision?.trim()),
    mission: Boolean(ov.mission?.trim()),
    mandate: Boolean(ov.mandate?.trim()),
    displayName: Boolean(ov.displayName?.trim()),
  };
  return {
    id: base.id,
    title: base.title,
    shortName: base.shortName,
    focusAreas: base.focusAreas,
    kpisOwned: base.kpisOwned,
    defaults: { vision: base.vision, mission: base.mission, mandate: base.mandate },
    vision: isOverridden.vision ? ov.vision!.trim() : base.vision,
    mission: isOverridden.mission ? ov.mission!.trim() : base.mission,
    mandate: isOverridden.mandate ? ov.mandate!.trim() : base.mandate,
    displayName: isOverridden.displayName ? ov.displayName!.trim() : base.shortName,
    isOverridden,
  };
}


export function memberInitials(member: Pick<BoardMember, "displayName" | "shortName">): string {
  const name = member.displayName.trim();
  if (!name) return member.shortName.slice(0, 3).toUpperCase();
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 3).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}


export function memberLabel(
  members: readonly Pick<BoardMember, "id" | "displayName" | "shortName">[],
  personaId: string,
): string {
  const found = members.find((m) => m.id === personaId);
  if (!found) return personaId ? personaId.toUpperCase() : "Board";
  return found.displayName === found.shortName
    ? found.shortName
    : `${found.displayName} (${found.shortName})`;
}
