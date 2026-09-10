import { useCallback, useMemo, useState } from "react";
import { FinanceDataLoadOrError } from "../FinanceDataStatus";
import { BoardActionsList } from "./BoardActionsList";
import { BoardApprovalsList } from "./BoardApprovalsList";
import { BoardBoundariesCard } from "./BoardBoundariesCard";
import { BoardHoldsList } from "./BoardHoldsList";
import { BoardLessonsList } from "./BoardLessonsList";
import { BoardReviewSection } from "./BoardReviewSection";
import { BoardBriefEditor } from "./BoardBriefEditor";
import { BoardCharterEditor } from "./BoardCharterEditor";
import { BoardChatOffcanvas } from "./BoardChatOffcanvas";
import { BoardHeaderStrip } from "./BoardHeaderStrip";
import { BoardMailView } from "./BoardMailView";
import { BoardReceivablesView } from "./BoardReceivablesView";
import { BoardMeetingHistory } from "./BoardMeetingHistory";
import { BoardMeetingPanel } from "./BoardMeetingPanel";
import { BoardMemberEditor } from "./BoardMemberEditor";
import { BoardMembersStrip } from "./BoardMembersStrip";
import { BoardSettingsCard } from "./BoardSettingsCard";
import { BoardMarketSection } from "./BoardMarketSection";
import { BoardStaffSection } from "./BoardStaffSection";
import { BoardToolsCard } from "./BoardToolsCard";
import { BoardUpdatesComposer } from "./BoardUpdatesComposer";
import { StartMeetingForm } from "./StartMeetingForm";
import { useBoardStaff } from "../../hooks/useBoardStaff";
import { useBoard, useBoardUpdates } from "../../hooks/useBoard";
import { useBoardActions } from "../../hooks/useBoardActions";
import { useBoardApprovals } from "../../hooks/useBoardApprovals";
import { useBoardBoundaries } from "../../hooks/useBoardBoundaries";
import { useBoardHolds } from "../../hooks/useBoardHolds";
import { useBoardReview } from "../../hooks/useBoardReview";
import { useBoardToolCalls, useBoardTools } from "../../hooks/useBoardTools";
import {
  useBoardMeeting,
  useBoardMeetings,
  useCancelBoardMeeting,
  useStartBoardMeeting,
  type StartMeetingVariables,
} from "../../hooks/useBoardMeetings";
import { AdminTabList, type AdminTabItem } from "../ui";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import { adminTabButtonId } from "../../lib/adminTabs";
import { DEFAULT_BOARD_BOUNDARIES, effectiveToolLevel, type BoardMeetingMode, type BoardOverview } from "../../lib/boardModel";

type BoardSection = "review" | "market" | "actions" | "staff" | "approvals" | "mail" | "receivables" | "meetings" | "members" | "brief" | "settings";

const CLOSED_MEETING = "__closed__";
const SECTION_ID_PREFIX = "board-section";
const SECTION_PANEL_ID = "board-section-panel";

const SECTIONS: readonly { readonly id: BoardSection; readonly label: string; readonly icon: string }[] = [
  { id: "review", label: "Daily review", icon: "bi-sun" },
  { id: "market", label: "Market", icon: "bi-binoculars" },
  { id: "actions", label: "Next actions", icon: "bi-list-check" },
  { id: "staff", label: "Staff", icon: "bi-people-fill" },
  { id: "approvals", label: "Approvals", icon: "bi-shield-check" },
  { id: "mail", label: "Mail", icon: "bi-envelope" },
  { id: "receivables", label: "Receivables", icon: "bi-receipt" },
  { id: "meetings", label: "Meetings", icon: "bi-people" },
  { id: "members", label: "Board members", icon: "bi-person-badge" },
  { id: "brief", label: "Charter & brief", icon: "bi-journal-richtext" },
  { id: "settings", label: "Settings", icon: "bi-gear" },
];

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

function sectionTabs(
  overview: BoardOverview | undefined,
  needsOwner: number,
): readonly AdminTabItem<BoardSection>[] {
  const counts: Partial<Record<BoardSection, { value: number; tone: "neutral" | "warning" }>> = {
    actions: { value: overview?.openActionCount ?? 0, tone: "neutral" },
    staff: { value: needsOwner, tone: "warning" },
    approvals: { value: overview?.pendingApprovalCount ?? 0, tone: "warning" },
    mail: { value: overview?.unreadMailCount ?? 0, tone: "neutral" },
    receivables: { value: overview?.overdueInvoiceCount ?? 0, tone: "warning" },
  };
  return SECTIONS.map((s) => {
    const count = counts[s.id];
    return {
      id: s.id,
      label: s.label,
      icon: s.icon,
      ...(count && count.value > 0 ? { badge: count } : {}),
    };
  });
}

export function ExecutiveBoardTab() {
  const board = useBoard();
  const updatesQuery = useBoardUpdates();
  const actions = useBoardActions();
  const meetingsQuery = useBoardMeetings();
  const startMeeting = useStartBoardMeeting();
  const cancelMeeting = useCancelBoardMeeting();
  const approvals = useBoardApprovals();
  const holds = useBoardHolds();
  const boundaries = useBoardBoundaries();
  const tools = useBoardTools();
  const staff = useBoardStaff();
  const lessons = useBoardReview(true);

  const urlSection = useMemo(() => {
    const requested = new URLSearchParams(window.location.search).get("section");
    if (requested && SECTIONS.some((s) => s.id === requested)) return requested as BoardSection;
    return null;
  }, []);
  const [pinnedSection, setPinnedSection] = useState<BoardSection | null>(urlSection);
  const [chatPersonaId, setChatPersonaId] = useState<string | null>(null);
  const [editPersonaId, setEditPersonaId] = useState<string | null>(null);
  // null = follow the running meeting (if any); CLOSED_MEETING = user closed the panel.
  const [selectedMeeting, setSelectedMeeting] = useState<string | null>(null);
  const [startForm, setStartForm] = useState<{ mode: BoardMeetingMode; topic: string } | null>(null);
  const [focusApprovalId, setFocusApprovalId] = useState<string | null>(null);
  const [focusThreadId, setFocusThreadId] = useState<string | null>(null);
  const [showCallLog, setShowCallLog] = useState(false);

  const overview = board.overview;
  const section: BoardSection =
    pinnedSection ?? (overview?.settings.staff?.enabled ? "review" : "actions");
  const setSection = useCallback((id: BoardSection) => {
    setPinnedSection(id);
  }, []);
  const callLog = useBoardToolCalls(section === "settings" && showCallLog);
  const members = overview?.members ?? [];
  const toolsConfig = tools.data?.config ?? overview?.settings.tools;
  const runningId = overview?.runningMeeting?.meetingId ?? null;
  const selectedMeetingId =
    selectedMeeting === CLOSED_MEETING ? null : selectedMeeting ?? runningId;
  const meetingQuery = useBoardMeeting(selectedMeetingId);

  const openActionsByPersona = useMemo(() => {
    const out: Record<string, number> = {};
    for (const a of actions.actions) {
      if (a.status === "open") out[a.persona] = (out[a.persona] ?? 0) + 1;
    }
    return out;
  }, [actions.actions]);

  const openMeeting = useCallback((meetingId: string) => {
    setSelectedMeeting(meetingId);
    setSection("meetings");
  }, [setSection]);

  const openApproval = useCallback((approvalId: string) => {
    setChatPersonaId(null);
    setFocusApprovalId(approvalId);
    setSection("approvals");
  }, [setSection]);

  const openMailThread = useCallback((threadId: string) => {
    setFocusThreadId(threadId);
    setSection("mail");
  }, [setSection]);

  const chatToolLabels = useMemo(() => {
    if (!chatPersonaId || !toolsConfig || !overview?.toolsEnabled) return [];
    const registry = tools.data?.registry ?? [];
    return registry
      .filter((t) => effectiveToolLevel(toolsConfig, t.id, chatPersonaId) !== "off")
      .map((t) => t.label);
  }, [chatPersonaId, toolsConfig, overview?.toolsEnabled, tools.data?.registry]);

  const runStandup = () => {
    startMeeting.mutate(
      { mode: "standup", chair: overview?.settings.defaultChair },
      { onSuccess: (m) => openMeeting(m.meetingId) },
    );
  };

  const startFromForm = (vars: StartMeetingVariables) => {
    startMeeting.mutate(vars, {
      onSuccess: (m) => {
        setStartForm(null);
        openMeeting(m.meetingId);
      },
    });
  };

  const planDeepDive = (topic = "") => {
    setStartForm({ mode: "deepDive", topic });
    setSection("meetings");
  };

  const chatMember = members.find((m) => m.id === chatPersonaId) ?? null;
  const editMember = members.find((m) => m.id === editPersonaId) ?? null;

  return (
    <div>
      <FinanceDataLoadOrError
        isLoading={board.isLoading}
        isError={board.isError}
        loadErrorMessage="Could not load the Executive Board. Check that the lxsoftware stack is deployed with the board routes."
        onRetry={() => void board.refetch()}
        isRetrying={board.isRefetching}
      />
      {!board.isLoading ? (
        <>
          {overview ? (
            <BoardHeaderStrip
              overview={overview}
              onRunStandup={runStandup}
              onPlanDeepDive={() => planDeepDive()}
              onOpenMeeting={openMeeting}
              isStarting={startMeeting.isPending}
              startError={errorText(startMeeting.error)}
            />
          ) : null}

          <AdminTabList
            tabs={sectionTabs(overview, staff.counts.needs_owner ?? 0)}
            active={section}
            onChange={setSection}
            label="Board sections"
            idPrefix={SECTION_ID_PREFIX}
            panelId={SECTION_PANEL_ID}
            disabled={!overview}
          />

          {!overview ? (
            <p className="text-muted small mb-0">
              Board sections open once the overview loads. Retry to continue.
            </p>
          ) : null}

          <div
            id={SECTION_PANEL_ID}
            role="tabpanel"
            aria-labelledby={adminTabButtonId(SECTION_ID_PREFIX, section)}
          >
          {overview && section === "review" ? <BoardReviewSection /> : null}

          {overview && section === "market" ? <BoardMarketSection /> : null}

          {overview && section === "actions" ? (
            <BoardActionsList
              actions={actions.actions}
              members={members}
              isLoading={actions.isLoading}
              onUpdate={(vars) => actions.update.mutate(vars)}
              onOpenMeeting={openMeeting}
            />
          ) : null}

          {overview && section === "staff" ? <BoardStaffSection /> : null}

          {overview && section === "approvals" ? (
            <>
              <BoardHoldsList
                holds={holds.holds}
                isLoading={holds.isLoading}
                isVetoing={holds.veto.isPending || holds.vetoClass.isPending}
                errorMessage={errorText(holds.error) ?? errorText(holds.veto.error) ?? errorText(holds.vetoClass.error)}
                onVeto={(holdId, reason) => holds.veto.mutate({ holdId, reason })}
                onVetoClass={(classKey) => holds.vetoClass.mutate(classKey)}
                onOpenMailThread={openMailThread}
              />
              <BoardApprovalsList
                approvals={approvals.approvals}
                members={members}
                isLoading={approvals.isLoading}
                isDeciding={approvals.decide.isPending}
                errorMessage={errorText(approvals.error) ?? errorText(approvals.decide.error)}
                onDecide={(vars) => approvals.decide.mutate(vars)}
                onOpenMeeting={openMeeting}
                onOpenMailThread={openMailThread}
                focusApprovalId={focusApprovalId}
              />
            </>
          ) : null}

          {overview && section === "mail" ? (
            <BoardMailView
              status={overview.mail}
              focusThreadId={focusThreadId}
              onFocusConsumed={() => setFocusThreadId(null)}
              errorText={errorText}
            />
          ) : null}

          {overview && section === "receivables" ? (
            <BoardReceivablesView overdueCount={overview.overdueInvoiceCount} errorText={errorText} />
          ) : null}

          {overview && section === "meetings" ? (
            <>
              {startForm ? (
                <StartMeetingForm
                  members={members}
                  defaultChair={overview.settings.defaultChair}
                  initialMode={startForm.mode}
                  initialTopic={startForm.topic}
                  isStarting={startMeeting.isPending}
                  onStart={startFromForm}
                  onCancel={() => setStartForm(null)}
                />
              ) : (
                <div className="d-flex gap-2 mb-3">
                  <button
                    type="button"
                    className="btn btn-outline-primary btn-sm"
                    disabled={Boolean(overview.runningMeeting)}
                    onClick={() => setStartForm({ mode: overview.settings.defaultMode, topic: "" })}
                  >
                    <i className="bi bi-plus-lg me-1" aria-hidden="true" />
                    New meeting…
                  </button>
                </div>
              )}
              {selectedMeetingId ? (
                <BoardMeetingPanel
                  data={meetingQuery.data}
                  isLoading={meetingQuery.isLoading}
                  members={members}
                  onCancel={(id) => cancelMeeting.mutate(id)}
                  isCancelling={cancelMeeting.isPending}
                  onClose={() => setSelectedMeeting(CLOSED_MEETING)}
                  onOpenApproval={openApproval}
                />
              ) : null}
              {cancelMeeting.error ? <div className="alert alert-danger py-2 small">{errorText(cancelMeeting.error)}</div> : null}
              <BoardMeetingHistory
                meetings={meetingsQuery.data ?? []}
                members={members}
                selectedMeetingId={selectedMeetingId}
                onOpen={openMeeting}
              />
            </>
          ) : null}

          {overview && section === "members" ? (
            <>
              <p className="text-muted small">
                Eight fixed roles. Each member argues from its own vision, mission and mandate; edit them to
                change how that member thinks. Chat with anyone; the chair can also propose a meeting.
              </p>
              <BoardMembersStrip
                members={members}
                chairId={overview.settings.defaultChair}
                openActionsByPersona={openActionsByPersona}
                onChat={setChatPersonaId}
                onEdit={setEditPersonaId}
              />
            </>
          ) : null}

          {overview && section === "brief" ? (
            <>
              <BoardCharterEditor
                key={`charter-${overview.charter.updatedAt ?? ""}`}
                charter={overview.charter}
                isSaving={board.saveCharter.isPending}
                errorMessage={errorText(board.saveCharter.error)}
                onSave={(c) => board.saveCharter.mutate(c)}
              />
              <BoardBriefEditor
                key={`brief-${overview.brief.updatedAt ?? ""}`}
                brief={overview.brief}
                isSaving={board.saveBrief.isPending}
                errorMessage={errorText(board.saveBrief.error)}
                onSave={(md) => board.saveBrief.mutate(md)}
              />
              <BoardUpdatesComposer
                updates={updatesQuery.data ?? []}
                isPosting={board.postUpdate.isPending}
                errorMessage={errorText(board.postUpdate.error)}
                onPost={(text) => board.postUpdate.mutate(text)}
              />
            </>
          ) : null}

          {overview && section === "settings" ? (
            <>
              {tools.data ? (
                <BoardToolsCard
                  key={`tools-${JSON.stringify(tools.data.config)}`}
                  payload={tools.data}
                  members={members}
                  isSaving={tools.save.isPending}
                  errorMessage={errorText(tools.save.error)}
                  onSave={(patch) => tools.save.mutate(patch)}
                  callLog={callLog.data}
                  isCallLogLoading={callLog.isLoading}
                  showCallLog={showCallLog}
                  onToggleCallLog={setShowCallLog}
                />
              ) : tools.isError ? (
                <div className="alert alert-danger py-2 small">{errorText(tools.error)}</div>
              ) : (
                <div className="card shadow-sm mb-4"><div className="card-body text-muted small">Loading tool permissions…</div></div>
              )}
              <BoardBoundariesCard
                key={`boundaries-${overview.settings.updatedAt ?? ""}`}
                boundaries={overview.settings.boundaries ?? DEFAULT_BOARD_BOUNDARIES}
                isSaving={boundaries.save.isPending}
                errorMessage={errorText(boundaries.save.error)}
                onSave={(next) => boundaries.save.mutate(next)}
              />
              <BoardLessonsList
                lessons={lessons.lessons}
                isMutating={lessons.confirmLesson.isPending || lessons.dismissLesson.isPending}
                errorMessage={errorText(lessons.confirmLesson.error) ?? errorText(lessons.dismissLesson.error)}
                onConfirm={(id, instruction) => lessons.confirmLesson.mutate({ lessonId: id, instruction })}
                onDismiss={(id) => lessons.dismissLesson.mutate(id)}
              />
              <BoardSettingsCard
                key={`settings-${overview.settings.updatedAt ?? ""}`}
                overview={overview}
                members={members}
                isSaving={board.saveSettings.isPending}
                errorMessage={errorText(board.saveSettings.error)}
                onSave={(patch) => board.saveSettings.mutate(patch)}
                onRefreshRepo={() => board.refreshRepoSnapshot.mutate()}
                isRefreshingRepo={board.refreshRepoSnapshot.isPending}
                refreshRepoError={errorText(board.refreshRepoSnapshot.error)}
              />
            </>
          ) : null}
          </div>

          {overview ? (
            <BoardChatOffcanvas
              member={chatMember}
              isChair={chatMember?.id === overview.settings.defaultChair}
              toolLabels={chatToolLabels}
              onOpenApproval={openApproval}
              onClose={() => setChatPersonaId(null)}
              onStartMeeting={(mode, topic) => {
                setChatPersonaId(null);
                if (mode === "standup" && !topic) runStandup();
                else {
                  setStartForm({ mode, topic });
                  setSection("meetings");
                }
              }}
            />
          ) : null}

          {overview && editMember ? (
          <BoardMemberEditor
            key={`${editMember.id}-${editMember.updatedAt ?? ""}`}
            member={editMember}
            charter={overview.charter}
            isSaving={board.saveMember.isPending || board.resetMember.isPending}
            errorMessage={errorText(board.saveMember.error) ?? errorText(board.resetMember.error)}
            onSave={(personaId, override) =>
              board.saveMember.mutate({ personaId, override }, { onSuccess: () => setEditPersonaId(null) })
            }
            onReset={(personaId) => board.resetMember.mutate(personaId, { onSuccess: () => setEditPersonaId(null) })}
            onClose={() => setEditPersonaId(null)}
          />
          ) : null}
        </>
      ) : null}
    </div>
  );
}
