import {
  BOARD_TOOL_LEVELS,
  type BoardToolGlobalMode,
  type BoardToolLevel,
} from "../contracts/generated";
import type { BoardApprovalStatus, BoardToolCallStatus, BoardToolsConfig } from "./types";


export const TOOL_LEVEL_LABELS: Readonly<Record<BoardToolLevel, string>> = {
  off: "Off",
  read: "Read",
  propose: "Propose",
  act: "Act",
};


export const TOOL_LEVEL_HELP: Readonly<Record<BoardToolLevel, string>> = {
  off: "No access to this tool.",
  read: "Look things up; never change anything.",
  propose: "Read, and queue writes for your approval.",
  act: "Read and write directly (logged).",
};


export const TOOL_GLOBAL_MODE_LABELS: Readonly<Record<BoardToolGlobalMode, string>> = {
  readOnly: "Read-only",
  propose: "Propose (writes need approval)",
  act: "Act (per-member levels apply)",
};


export const TOOL_LEVEL_BADGE_CLASS: Readonly<Record<BoardToolLevel, string>> = {
  off: "text-bg-light border text-muted",
  read: "text-bg-secondary",
  propose: "text-bg-warning",
  act: "text-bg-success",
};


export const TOOL_CALL_STATUS_ICON: Readonly<Record<BoardToolCallStatus, { readonly icon: string; readonly className: string; readonly label: string }>> = {
  ok: { icon: "bi-check-circle-fill", className: "text-success", label: "done" },
  error: { icon: "bi-x-circle-fill", className: "text-danger", label: "failed" },
  pending_approval: { icon: "bi-hourglass-split", className: "text-warning", label: "awaiting approval" },
  held: { icon: "bi-clock-history", className: "text-info", label: "scheduled" },
};


export const APPROVAL_STATUS_BADGE_CLASS: Readonly<Record<BoardApprovalStatus, string>> = {
  pending: "text-bg-warning",
  approved: "text-bg-info",
  executed: "text-bg-success",
  rejected: "text-bg-secondary",
  failed: "text-bg-danger",
};


/** Levels above the tool's own ceiling (e.g. read-only connectors) are not offered. */
export function levelsUpTo(maxLevel: BoardToolLevel): readonly BoardToolLevel[] {
  const idx = BOARD_TOOL_LEVELS.indexOf(maxLevel);
  return BOARD_TOOL_LEVELS.slice(0, idx + 1);
}


/** Mirrors `board_tools.effective_level`: the global mode caps every configured level. */
export function effectiveToolLevel(config: BoardToolsConfig, toolId: string, personaId: string): BoardToolLevel {
  if (!config.enabled) return "off";
  const configured = config.matrix[toolId]?.[personaId] ?? "off";
  const cap: BoardToolLevel = config.globalMode === "readOnly" ? "read" : config.globalMode === "propose" ? "propose" : "act";
  return BOARD_TOOL_LEVELS.indexOf(configured) <= BOARD_TOOL_LEVELS.indexOf(cap) ? configured : cap;
}
