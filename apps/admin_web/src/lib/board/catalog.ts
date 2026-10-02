import { BOARD_CATALOG_EVENT_KINDS } from "../contracts/generated";
import type { BoardCatalogImportPreview, BoardTask } from "./types";


export const CATALOG_MAX_REVALIDATE_ATTEMPTS = 3;


export function canImportCatalogTask(task: Pick<BoardTask, "status" | "importedAt" | "importPhase">): boolean {
  if (task.importedAt) return false;
  if (task.status === "awaiting_import") return task.importPhase !== "collision";
  return task.status === "needs_owner" && Boolean(task.importPhase) && task.importPhase !== "collision";
}


export function canForceCatalogImport(task: Pick<BoardTask, "status" | "importedAt" | "importPhase">): boolean {
  return !task.importedAt && task.importPhase === "collision";
}


export function canSkipCatalogTask(task: Pick<BoardTask, "status" | "importedAt">): boolean {
  return !task.importedAt && (task.status === "awaiting_import" || task.status === "needs_owner");
}


export function canRequeueCatalogImport(task: Pick<BoardTask, "status" | "importPhase">): boolean {
  return task.status === "needs_owner" && Boolean(task.importPhase);
}


export function canReimportCatalogTask(
  task: Pick<BoardTask, "importedAt" | "importPhase" | "importResult" | "eventRef">,
): boolean {
  if (!isCatalogSheetTask(task)) return false;
  const imported = Boolean(task.importedAt) || task.importPhase === "imported";
  const partial = task.importPhase === "partial";
  if (imported) return true;
  if (!partial) return false;
  const stored = task.importResult?.failedActivities;
  if (typeof stored === "number") return stored > 0;
  return (task.importResult?.results ?? []).some(
    (row) => row.type === "activities" && row.status === "failed",
  );
}


export function showTaskReviewActions(task: Pick<BoardTask, "status" | "importPhase" | "eventRef">): boolean {
  if (task.status === "review") return true;
  if (task.status !== "needs_owner") return false;
  return !(isCatalogSheetTask(task) && task.importPhase);
}


export function isCatalogSheetTask(task: Pick<BoardTask, "eventRef"> | undefined | null): boolean {
  const kind = task?.eventRef?.kind;
  return Boolean(kind && (BOARD_CATALOG_EVENT_KINDS as readonly string[]).includes(kind));
}


/** Use a live preview mutation only when it belongs to the open task. */
export function liveCatalogPreviewForTask(
  live: BoardCatalogImportPreview | null | undefined,
  taskId: string | null | undefined,
  fallback?: BoardCatalogImportPreview | null,
): BoardCatalogImportPreview | null | undefined {
  if (live && taskId && live.taskId === taskId) return live;
  return fallback;
}


/** Surface a catalog mutation error only when it belongs to the open task. */
export function catalogMutationErrorForTask(
  variables: unknown,
  taskId: string | null | undefined,
  error: unknown,
  format: (err: unknown) => string | null,
): string | null {
  if (!taskId) return null;
  if (variables === taskId) return format(error);
  if (
    variables &&
    typeof variables === "object" &&
    "taskId" in variables &&
    (variables as { taskId?: string }).taskId === taskId
  ) {
    return format(error);
  }
  return null;
}


/** First catalog mutation error that belongs to the open task (preview / import / skip / requeue). */
export function catalogDrawerMessageForTask(
  taskId: string | null | undefined,
  sources: readonly { readonly variables?: unknown; readonly error?: unknown }[],
  format: (err: unknown) => string | null,
): string | null {
  for (const source of sources) {
    const message = catalogMutationErrorForTask(source.variables, taskId, source.error, format);
    if (message) return message;
  }
  return null;
}


export const CATALOG_MUTATION_KEYS = ["preview", "import", "skip", "requeue", "reimport"] as const;

export type CatalogMutationKey = (typeof CATALOG_MUTATION_KEYS)[number];


/** Other catalog mutations to reset after one of them succeeds. */
export function catalogSiblingMutationKeys(keep: CatalogMutationKey): readonly CatalogMutationKey[] {
  return CATALOG_MUTATION_KEYS.filter((key) => key !== keep);
}
