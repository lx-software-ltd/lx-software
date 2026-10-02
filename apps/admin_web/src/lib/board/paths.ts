import type { BoardCatalogCandidateQuery } from "./types";

export const BOARD_API_BASE = "/siu-tin-dei/board";




export function boardMemberPath(personaId: string): string {
  return `${BOARD_API_BASE}/members/${encodeURIComponent(personaId)}`;
}


export function boardChatPath(personaId: string): string {
  return `${BOARD_API_BASE}/chat/${encodeURIComponent(personaId)}`;
}


export function boardChatJobPath(personaId: string, jobId: string): string {
  return `${boardChatPath(personaId)}/jobs/${encodeURIComponent(jobId)}`;
}


export function boardMeetingPath(meetingId: string): string {
  return `${BOARD_API_BASE}/meetings/${encodeURIComponent(meetingId)}`;
}


export function boardActionPath(actionId: string): string {
  return `${BOARD_API_BASE}/actions/${encodeURIComponent(actionId)}`;
}


export function boardApprovalDecisionPath(approvalId: string, decision: "approve" | "reject"): string {
  return `${BOARD_API_BASE}/approvals/${encodeURIComponent(approvalId)}/${decision}`;
}


export function boardMailThreadPath(threadId: string): string {
  return `${BOARD_API_BASE}/mail/${encodeURIComponent(threadId)}`;
}


export function boardStaffPath(seatId?: string): string {
  return seatId ? `${BOARD_API_BASE}/staff/${encodeURIComponent(seatId)}` : `${BOARD_API_BASE}/staff`;
}


export function boardStaffTickPath(): string {
  return `${BOARD_API_BASE}/staff/tick`;
}


export function boardTasksPath(query?: { status?: string; assignee?: string; limit?: number }): string {
  const params = new URLSearchParams();
  if (query?.status) params.set("status", query.status);
  if (query?.assignee) params.set("assignee", query.assignee);
  if (query?.limit) params.set("limit", String(query.limit));
  const qs = params.toString();
  return qs ? `${BOARD_API_BASE}/tasks?${qs}` : `${BOARD_API_BASE}/tasks`;
}


export function boardTaskPath(taskId: string): string {
  return `${BOARD_API_BASE}/tasks/${encodeURIComponent(taskId)}`;
}


export function boardTaskCancelPath(taskId: string): string {
  return `${boardTaskPath(taskId)}/cancel`;
}


export function boardTaskReviewPath(taskId: string): string {
  return `${boardTaskPath(taskId)}/review`;
}


export function boardTaskRetryPath(taskId: string): string {
  return `${boardTaskPath(taskId)}/retry`;
}


export function boardHoldsPath(query?: { status?: string; limit?: number }): string {
  const params = new URLSearchParams();
  if (query?.status) params.set("status", query.status);
  if (query?.limit) params.set("limit", String(query.limit));
  const qs = params.toString();
  return qs ? `${BOARD_API_BASE}/holds?${qs}` : `${BOARD_API_BASE}/holds`;
}


export function boardHoldVetoPath(holdId: string): string {
  return `${BOARD_API_BASE}/holds/${encodeURIComponent(holdId)}/veto`;
}


export function boardHoldVetoClassPath(): string {
  return `${BOARD_API_BASE}/holds/veto-class`;
}


export function boardBoundariesPath(): string {
  return `${BOARD_API_BASE}/boundaries`;
}


export function boardRampPath(): string {
  return `${BOARD_API_BASE}/ramp`;
}


export function boardRampPromotePath(classKey: string): string {
  return `${BOARD_API_BASE}/ramp/${encodeURIComponent(classKey)}/promote`;
}


export function boardReviewPath(date?: string): string {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  const qs = params.toString();
  return qs ? `${BOARD_API_BASE}/review?${qs}` : `${BOARD_API_BASE}/review`;
}


export function boardProgressPath(): string {
  return `${BOARD_API_BASE}/progress`;
}


export function boardReviewWrongPath(callId: string): string {
  return `${BOARD_API_BASE}/review/sample/${encodeURIComponent(callId)}/wrong`;
}


export function boardLessonsPath(): string {
  return `${BOARD_API_BASE}/lessons`;
}


export function boardLessonConfirmPath(lessonId: string): string {
  return `${BOARD_API_BASE}/lessons/${encodeURIComponent(lessonId)}/confirm`;
}


export function boardLessonDismissPath(lessonId: string): string {
  return `${BOARD_API_BASE}/lessons/${encodeURIComponent(lessonId)}/dismiss`;
}


export function boardBreakersPath(): string {
  return `${BOARD_API_BASE}/breakers`;
}


export function boardWatchlistPath(): string {
  return `${BOARD_API_BASE}/watchlist`;
}


export function boardWatchPath(watchId: string): string {
  return `${BOARD_API_BASE}/watchlist/${encodeURIComponent(watchId)}`;
}


export function boardProspectsPath(query?: {
  readonly stage?: string;
  readonly type?: string;
  readonly district?: string;
  readonly limit?: number;
}): string {
  const params = new URLSearchParams();
  if (query?.stage) params.set("stage", query.stage);
  if (query?.type) params.set("type", query.type);
  if (query?.district) params.set("district", query.district);
  if (query?.limit) params.set("limit", String(query.limit));
  const qs = params.toString();
  return qs ? `${BOARD_API_BASE}/prospects?${qs}` : `${BOARD_API_BASE}/prospects`;
}


export function boardProspectPath(prospectId: string): string {
  return `${BOARD_API_BASE}/prospects/${encodeURIComponent(prospectId)}`;
}


export function boardProspectImportPath(): string {
  return `${BOARD_API_BASE}/prospects/import`;
}


export function boardProspectMergePath(prospectId: string): string {
  return `${BOARD_API_BASE}/prospects/${encodeURIComponent(prospectId)}/merge`;
}


export function boardSequencePath(type: string): string {
  return `${BOARD_API_BASE}/sequences/${encodeURIComponent(type)}`;
}


export function boardContentPath(query?: {
  readonly from?: string;
  readonly to?: string;
  readonly status?: string;
}): string {
  const params = new URLSearchParams();
  if (query?.from) params.set("from", query.from);
  if (query?.to) params.set("to", query.to);
  if (query?.status) params.set("status", query.status);
  const qs = params.toString();
  return qs ? `${BOARD_API_BASE}/content?${qs}` : `${BOARD_API_BASE}/content`;
}


export function boardContentItemPath(contentId: string): string {
  return `${BOARD_API_BASE}/content/${encodeURIComponent(contentId)}`;
}


export function boardContentRenderPath(contentId: string): string {
  return `${BOARD_API_BASE}/content/${encodeURIComponent(contentId)}/render`;
}


export function boardContentCreativePath(contentId: string, n: number): string {
  return `${BOARD_API_BASE}/content/${encodeURIComponent(contentId)}/creative/${n}`;
}


export function boardCodeStagingPath(): string {
  return `${BOARD_API_BASE}/code/staging`;
}


export function boardCodePromotePath(): string {
  return `${BOARD_API_BASE}/code/promote`;
}


export function boardCodeSyncStagingPath(): string {
  return `${BOARD_API_BASE}/code/sync-staging`;
}


export function boardCatalogPreviewPath(): string {
  return `${BOARD_API_BASE}/catalog/preview`;
}


export function boardCatalogImportPath(): string {
  return `${BOARD_API_BASE}/catalog/import`;
}


export function boardCatalogSkipPath(): string {
  return `${BOARD_API_BASE}/catalog/skip`;
}


export function boardCatalogRequeuePath(): string {
  return `${BOARD_API_BASE}/catalog/requeue`;
}


export function boardCatalogReimportPath(): string {
  return `${BOARD_API_BASE}/catalog/reimport`;
}


export function boardCatalogSourcesPath(): string {
  return `${BOARD_API_BASE}/catalog/sources`;
}


export function boardCatalogBulkPreviewPath(source: string): string {
  return `${BOARD_API_BASE}/catalog/bulk/${encodeURIComponent(source)}/preview`;
}


export function boardCatalogBulkImportPath(source: string): string {
  return `${BOARD_API_BASE}/catalog/bulk/${encodeURIComponent(source)}/import`;
}


export function boardCatalogCandidatesPath(query?: string | BoardCatalogCandidateQuery): string {
  const filters: BoardCatalogCandidateQuery = typeof query === "string" ? { status: query } : query ?? {};
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.source) params.set("source", filters.source);
  if (filters.district) params.set("district", filters.district);
  if (filters.q) params.set("q", filters.q);
  if (filters.missingPlaceId) params.set("missingPlaceId", "true");
  if (filters.limit != null) params.set("limit", String(filters.limit));
  if (filters.cursor != null) params.set("cursor", String(filters.cursor));
  const qs = params.toString();
  return qs ? `${BOARD_API_BASE}/catalog/candidates?${qs}` : `${BOARD_API_BASE}/catalog/candidates`;
}


export function boardCatalogCandidatesBulkPath(): string {
  return `${BOARD_API_BASE}/catalog/candidates/bulk`;
}


export function boardCatalogCandidateDecidePath(candidateId: string, decision: "approve" | "reject"): string {
  return `${BOARD_API_BASE}/catalog/candidates/${encodeURIComponent(candidateId)}/${decision}`;
}


export function boardCatalogDiscoveryRunPath(): string {
  return `${BOARD_API_BASE}/catalog/discovery/run`;
}


export function boardOutreachStatsPath(days?: number): string {
  const params = new URLSearchParams();
  if (days) params.set("days", String(days));
  const qs = params.toString();
  return qs ? `${BOARD_API_BASE}/outreach/stats?${qs}` : `${BOARD_API_BASE}/outreach/stats`;
}


export function boardChangesPath(days?: number): string {
  const params = new URLSearchParams();
  if (days) params.set("days", String(days));
  const qs = params.toString();
  return qs ? `${BOARD_API_BASE}/changes?${qs}` : `${BOARD_API_BASE}/changes`;
}


export function boardBreakerResetPath(name: string): string {
  return `${BOARD_API_BASE}/breakers/${encodeURIComponent(name)}/reset`;
}
