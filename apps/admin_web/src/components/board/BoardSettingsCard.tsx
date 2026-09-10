import { useState } from "react";
import { AdminEditorSection, DateTimeDisplay } from "../ui";
import {
  formatUsageCost,
  MEETING_MODE_LABELS,
  memberLabel,
  type BoardMeetingMode,
  type BoardMember,
  type BoardOverview,
  type BoardSettings,
} from "../../lib/boardModel";
import { BOARD_MAX_DAILY_BUDGET_USD } from "../../lib/contracts/generated";

export type BoardSettingsCardProps = {
  readonly overview: BoardOverview;
  readonly members: readonly BoardMember[];
  readonly isSaving: boolean;
  readonly errorMessage?: string | null;
  readonly onSave: (patch: Partial<BoardSettings>) => void;
  readonly onRefreshRepo: () => void;
  readonly isRefreshingRepo: boolean;
  readonly refreshRepoError?: string | null;
};

export function BoardSettingsCard({
  overview,
  members,
  isSaving,
  errorMessage,
  onSave,
  onRefreshRepo,
  isRefreshingRepo,
  refreshRepoError,
}: BoardSettingsCardProps) {
  const { settings } = overview;
  const [draft, setDraft] = useState<BoardSettings>(settings);

  const isDirty = JSON.stringify(draft) !== JSON.stringify(settings);

  return (
    <AdminEditorSection
      title="Settings"
      description="Schedule, defaults, what the board is allowed to read, models and the daily spend cap."
      footer={
        <>
          <button type="button" className="btn btn-primary" disabled={!isDirty || isSaving} onClick={() => onSave(draft)}>
            {isSaving ? "Saving…" : "Save settings"}
          </button>
          {settings.updatedAt ? (
            <span className="small text-muted">
              Saved <DateTimeDisplay iso={settings.updatedAt} />
            </span>
          ) : null}
          {errorMessage ? <span className="small text-danger">{errorMessage}</span> : null}
        </>
      }
    >
      <div className="row g-4">
        <div className="col-12 col-lg-6">
          <h3 className="h6">Scheduled stand-ups</h3>
          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-schedule-morning"
              checked={draft.schedule.morningEnabled}
              onChange={(ev) => setDraft((d) => ({ ...d, schedule: { ...d.schedule, morningEnabled: ev.target.checked } }))}
            />
            <label className="form-check-label" htmlFor="board-schedule-morning">Every day at 06:00 HKT</label>
          </div>
          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-schedule-evening"
              checked={draft.schedule.eveningEnabled}
              onChange={(ev) => setDraft((d) => ({ ...d, schedule: { ...d.schedule, eveningEnabled: ev.target.checked } }))}
            />
            <label className="form-check-label" htmlFor="board-schedule-evening">Also at 18:00 HKT</label>
          </div>
          <div className="form-text">Scheduled meetings use the default format and chair below and skip when the budget is exhausted.</div>

          <h3 className="h6 mt-4">Defaults</h3>
          <div className="row g-2">
            <div className="col-6">
              <label className="form-label small" htmlFor="board-default-mode">Format</label>
              <select
                id="board-default-mode"
                className="form-select form-select-sm"
                value={draft.defaultMode}
                onChange={(ev) => setDraft((d) => ({ ...d, defaultMode: ev.target.value as BoardMeetingMode }))}
              >
                {(Object.keys(MEETING_MODE_LABELS) as BoardMeetingMode[]).map((m) => (
                  <option key={m} value={m}>{MEETING_MODE_LABELS[m]}</option>
                ))}
              </select>
            </div>
            <div className="col-6">
              <label className="form-label small" htmlFor="board-default-chair">Chair</label>
              <select
                id="board-default-chair"
                className="form-select form-select-sm"
                value={draft.defaultChair}
                onChange={(ev) => setDraft((d) => ({ ...d, defaultChair: ev.target.value }))}
              >
                {members.map((m) => (
                  <option key={m.id} value={m.id}>{memberLabel(members, m.id)}</option>
                ))}
              </select>
            </div>
          </div>

          <h3 className="h6 mt-4">Context the board may read</h3>
          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-share-finance"
              checked={draft.shareFinanceSummary}
              onChange={(ev) => setDraft((d) => ({ ...d, shareFinanceSummary: ev.target.checked }))}
            />
            <label className="form-check-label" htmlFor="board-share-finance">
              Finance summary <span className="text-muted small">(aggregated totals only from the Siu Tin Dei and LX Software books)</span>
            </label>
          </div>
          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-share-repo"
              checked={draft.shareRepoSnapshot}
              disabled={!overview.repoSnapshotEnabled}
              onChange={(ev) => setDraft((d) => ({ ...d, shareRepoSnapshot: ev.target.checked }))}
            />
            <label className="form-check-label" htmlFor="board-share-repo">
              Repository snapshot <span className="text-muted small">({overview.repo}: README, docs, open issues, recent commits, CI)</span>
            </label>
          </div>
          {!overview.repoSnapshotEnabled ? (
            <div className="form-text">
              The repository snapshot is unavailable on this stack.
            </div>
          ) : (
            <div className="small text-muted mt-1 d-flex flex-wrap gap-2 align-items-center">
              {overview.repoSnapshot ? (
                <span>
                  Snapshot from <DateTimeDisplay iso={overview.repoSnapshot.fetchedAt} /> · {overview.repoSnapshot.openIssuesCount} open issues ·{" "}
                  {overview.repoSnapshot.docs.length} docs · {overview.repoSnapshot.chars.toLocaleString()} chars
                </span>
              ) : (
                <span>No snapshot yet.</span>
              )}
              <button type="button" className="btn btn-sm btn-outline-secondary" disabled={isRefreshingRepo} onClick={onRefreshRepo}>
                {isRefreshingRepo ? "Refreshing…" : "Refresh now"}
              </button>
              {refreshRepoError ? <span className="text-danger">{refreshRepoError}</span> : null}
            </div>
          )}
          <div className="form-text">
            The snapshot is a once-a-day summary. Live lookups (issues, CI, files, security alerts) are governed per member under Tools &amp; permissions above.
          </div>
        </div>

        <div className="col-12 col-lg-6">
          <h3 className="h6">Models (OpenRouter slugs)</h3>
          {(["chat", "standup", "deepDive"] as const).map((kind) => (
            <div className="mb-2" key={kind}>
              <label className="form-label small mb-1" htmlFor={`board-model-${kind}`}>
                {kind === "chat" ? "Chat" : kind === "standup" ? "Stand-up meetings" : "Deep-dive meetings"}
              </label>
              <input
                id={`board-model-${kind}`}
                className="form-control form-control-sm"
                value={draft.models[kind]}
                placeholder={`default: ${overview.models[kind]}`}
                onChange={(ev) => setDraft((d) => ({ ...d, models: { ...d.models, [kind]: ev.target.value } }))}
              />
            </div>
          ))}
          <div className="form-text">Leave blank to use the stack defaults. Requests are routed only to providers that do not retain prompts.</div>

          <h3 className="h6 mt-4">Staff and daily review</h3>
          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-staff-enabled"
              checked={Boolean(draft.staff?.enabled)}
              disabled={Boolean(settings.staff?.disabledReason)}
              onChange={(ev) =>
                setDraft((d) => ({
                  ...d,
                  staff: {
                    enabled: ev.target.checked,
                    maxRunningTasks: d.staff?.maxRunningTasks ?? 6,
                    dailyBudgetUsd: d.staff?.dailyBudgetUsd ?? 20,
                    dutiesEnabled: d.staff?.dutiesEnabled,
                    seniorPaused: d.staff?.seniorPaused,
                    disabledReason: d.staff?.disabledReason,
                  },
                }))
              }
            />
            <label className="form-check-label" htmlFor="board-staff-enabled">
              Enable staff tasks
            </label>
          </div>
          {settings.staff?.disabledReason ? (
            <div className="form-text text-danger" id="board-staff-disabled-reason">
              Staff is disabled: {settings.staff.disabledReason}. Reset the budget breaker from the review page before turning staff back on.
            </div>
          ) : null}
          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-duties-enabled"
              checked={Boolean(draft.staff?.dutiesEnabled)}
              onChange={(ev) =>
                setDraft((d) => ({
                  ...d,
                  staff: {
                    enabled: Boolean(d.staff?.enabled),
                    maxRunningTasks: d.staff?.maxRunningTasks ?? 6,
                    dailyBudgetUsd: d.staff?.dailyBudgetUsd ?? 20,
                    dutiesEnabled: ev.target.checked,
                    seniorPaused: d.staff?.seniorPaused,
                  },
                }))
              }
            />
            <label className="form-check-label" htmlFor="board-duties-enabled">
              Run scheduled seat duties
            </label>
          </div>
          <div className="mb-2 mt-2">
            <label className="form-label small" htmlFor="board-review-digest">Digest email</label>
            <input
              id="board-review-digest"
              className="form-control form-control-sm"
              type="email"
              value={draft.review?.digestTo ?? ""}
              placeholder="founder@example.com"
              onChange={(ev) =>
                setDraft((d) => ({
                  ...d,
                  review: {
                    digestTo: ev.target.value,
                    digestHourHkt: d.review?.digestHourHkt ?? 7,
                    sampleSize: d.review?.sampleSize ?? 8,
                  },
                }))
              }
            />
            <div className="form-text">One address. Sent from board@siutindei.com at 07:30 HKT when mail sending is on.</div>
          </div>

          <h3 className="h6 mt-4">Daily budget</h3>
          <div className="input-group input-group-sm board-budget-input">
            <span className="input-group-text">USD</span>
            <input
              type="number"
              className="form-control"
              min={0}
              max={BOARD_MAX_DAILY_BUDGET_USD}
              step={0.5}
              value={draft.dailyBudgetUsd}
              aria-label="Daily budget in USD"
              onChange={(ev) => setDraft((d) => ({ ...d, dailyBudgetUsd: Number(ev.target.value) }))}
            />
            <span className="input-group-text">/ day</span>
          </div>
          <div className="form-text">
            Spent today: {formatUsageCost(overview.usageToday.cost)} over {overview.usageToday.calls ?? 0} calls. Chats and meetings are refused once the cap is reached (resets at midnight UTC). Set 0 to disable the cap.
          </div>
          {overview.usageToday.external ? (
            <div className="form-text">
              External APIs: {overview.usageToday.external.searchCalls} web searches today · Meta ads USD{" "}
              {overview.usageToday.external.metaAdsMonthUsd.toFixed(2)} this month
            </div>
          ) : null}
        </div>
      </div>
    </AdminEditorSection>
  );
}
