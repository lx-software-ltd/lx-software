import { useState } from "react";
import { AdminEditorSection, DateTimeDisplay } from "../ui";
import {
  formatUsageCost,
  MEETING_MODE_LABELS,
  memberLabel,
  catalogDraft,
  staffDraft,
  type BoardMeetingMode,
  type BoardMember,
  type BoardOverview,
  type BoardSettings,
} from "../../lib/boardModel";
import {
  BOARD_CATALOG_LAUNCH_LISTING_TARGET,
  BOARD_MAX_DAILY_BUDGET_USD,
  BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD,
  BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT,
} from "../../lib/contracts/generated";

/** Matches `normalize_staff_config` in `board_store.py`. */
const STAFF_MAX_RUNNING_TASKS_CAP = 20;
const STAFF_DAILY_BUDGET_MAX_USD = 100;

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
          <div className="form-text">
            Leave blank to use the stack defaults. Requests are routed only to providers that do not retain prompts.
            If a model is rate-limited upstream (common for DeepSeek shared pools), the board automatically tries
            the other board models, then openai/gpt-4.1-mini and anthropic/claude-sonnet-4.
          </div>

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
                  staff: staffDraft(d, { enabled: ev.target.checked }),
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
                  staff: staffDraft(d, { dutiesEnabled: ev.target.checked }),
                }))
              }
            />
            <label className="form-check-label" htmlFor="board-duties-enabled">
              Run scheduled seat duties
            </label>
          </div>
          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-catalog-auto-import"
              checked={Boolean(draft.catalog?.autoImport)}
              onChange={(ev) =>
                setDraft((d) => ({
                  ...d,
                  catalog: catalogDraft(d, { autoImport: ev.target.checked }),
                }))
              }
            />
            <label className="form-check-label" htmlFor="board-catalog-auto-import">
              Auto-import validated catalog sheets (24 h hold)
            </label>
          </div>
          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-catalog-micro-batch"
              checked={draft.catalog?.microBatchEnabled !== false}
              onChange={(ev) =>
                setDraft((d) => ({
                  ...d,
                  catalog: catalogDraft(d, { microBatchEnabled: ev.target.checked }),
                }))
              }
            />
            <label className="form-check-label" htmlFor="board-catalog-micro-batch">
              Run 3-per-district catalog micro-batch (pause while bulk import fills the catalog)
            </label>
          </div>
          <div className="mt-2">
            <label className="form-label small" htmlFor="board-catalog-launch-target">
              Launch listing target
            </label>
            <input
              id="board-catalog-launch-target"
              type="number"
              min={0}
              max={100000}
              className="form-control form-control-sm"
              value={draft.catalog?.launchListingTarget ?? BOARD_CATALOG_LAUNCH_LISTING_TARGET}
              onChange={(ev) => {
                const next = Number(ev.target.value);
                if (!Number.isFinite(next) || next < 0) return;
                setDraft((d) => ({
                  ...d,
                  catalog: catalogDraft(d, { launchListingTarget: Math.round(next) }),
                }));
              }}
            />
            <div className="form-text">
              Auto-import stops when venue-linked providers reach this number. Providers with no venue do not count.
            </div>
          </div>
          <div className="row g-2 mt-2">
            <div className="col-6">
              <label className="form-label small" htmlFor="board-staff-max-running">
                Concurrent tasks
              </label>
              <input
                id="board-staff-max-running"
                type="number"
                className="form-control form-control-sm"
                min={1}
                max={STAFF_MAX_RUNNING_TASKS_CAP}
                step={1}
                value={draft.staff?.maxRunningTasks ?? BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT}
                onChange={(ev) =>
                  setDraft((d) => ({
                    ...d,
                    staff: staffDraft(d, { maxRunningTasks: Number(ev.target.value) }),
                  }))
                }
              />
              <div className="form-text">
                How many staff tasks may run at once (1–{STAFF_MAX_RUNNING_TASKS_CAP}). Extra work stays queued until a slot frees.
              </div>
            </div>
            <div className="col-6">
              <label className="form-label small" htmlFor="board-staff-daily-budget">
                Staff daily budget
              </label>
              <div className="input-group input-group-sm">
                <span className="input-group-text">USD</span>
                <input
                  id="board-staff-daily-budget"
                  type="number"
                  className="form-control"
                  min={0}
                  max={STAFF_DAILY_BUDGET_MAX_USD}
                  step={0.5}
                  value={draft.staff?.dailyBudgetUsd ?? BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD}
                  aria-label="Staff daily budget in USD"
                  onChange={(ev) =>
                    setDraft((d) => ({
                      ...d,
                      staff: staffDraft(d, { dailyBudgetUsd: Number(ev.target.value) }),
                    }))
                  }
                />
                <span className="input-group-text">/ day</span>
              </div>
              <div className="form-text">
                Separate from the board chat and meeting cap below. Exhausted staff budget re-queues work instead of failing it.
              </div>
            </div>
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
