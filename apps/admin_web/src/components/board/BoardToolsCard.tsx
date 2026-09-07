import { useState } from "react";
import { AdminEditorSection, DateTimeDisplay } from "../ui";
import { BoardToolCallList } from "./BoardToolCallList";
import {
  effectiveToolLevel,
  formatUsageCost,
  levelsUpTo,
  MAIL_ALLOW_LIST_ENTRY_RE,
  memberLabel,
  parseAllowListText,
  TOOL_GLOBAL_MODE_LABELS,
  TOOL_LEVEL_BADGE_CLASS,
  TOOL_LEVEL_HELP,
  TOOL_LEVEL_LABELS,
  type BoardMember,
  type BoardSpendCaps,
  type BoardToolCallLogEntry,
  type BoardToolGlobalMode,
  type BoardToolLevel,
  type BoardToolsConfig,
  type BoardToolsPayload,
} from "../../lib/boardModel";
import {
  BOARD_MAIL_ALLOW_LIST_MAX_ENTRIES,
  BOARD_META_ADS_DAILY_CAP_USD,
  BOARD_META_ADS_MONTHLY_CAP_USD,
  BOARD_TOOL_GLOBAL_MODES,
} from "../../lib/contracts/generated";
import type { ToolsConfigPatch } from "../../hooks/useBoardTools";

export type BoardToolsCardProps = {
  readonly payload: BoardToolsPayload;
  readonly members: readonly BoardMember[];
  readonly isSaving: boolean;
  readonly errorMessage?: string | null;
  readonly onSave: (patch: ToolsConfigPatch) => void;
  readonly callLog: readonly BoardToolCallLogEntry[] | undefined;
  readonly isCallLogLoading: boolean;
  readonly showCallLog: boolean;
  readonly onToggleCallLog: (show: boolean) => void;
};

export function BoardToolsCard({
  payload,
  members,
  isSaving,
  errorMessage,
  onSave,
  callLog,
  isCallLogLoading,
  showCallLog,
  onToggleCallLog,
}: BoardToolsCardProps) {
  const {
    config,
    registry,
    defaults,
    envDisabled,
    repoWriteEnabled,
    mailSendEnabled,
    mailDomain,
    searchConfigured,
    dataApiConfigured,
    metaConfigured,
    storesConfigured,
    webConfigured,
    adsSpend,
  } = payload;
  const [draft, setDraft] = useState<BoardToolsConfig>(() => ({
    ...config,
    spendCaps: {
      metaAdsDailyUsd: config.spendCaps?.metaAdsDailyUsd ?? defaults.spendCaps?.metaAdsDailyUsd ?? BOARD_META_ADS_DAILY_CAP_USD,
      metaAdsMonthlyUsd:
        config.spendCaps?.metaAdsMonthlyUsd ?? defaults.spendCaps?.metaAdsMonthlyUsd ?? BOARD_META_ADS_MONTHLY_CAP_USD,
    },
  }));
  const [allowListText, setAllowListText] = useState(() => config.allowList.join("\n"));
  const draftAllowList = parseAllowListText(allowListText);
  const isDirty =
    JSON.stringify(draft) !== JSON.stringify(config) ||
    JSON.stringify(draftAllowList) !== JSON.stringify([...config.allowList]);
  const invalidAllowEntries = draftAllowList.filter((e) => !MAIL_ALLOW_LIST_ENTRY_RE.test(e));
  const tooManyAllowEntries = draftAllowList.length > BOARD_MAIL_ALLOW_LIST_MAX_ENTRIES;

  const setCell = (toolId: string, personaId: string, level: BoardToolLevel) =>
    setDraft((d) => ({ ...d, matrix: { ...d.matrix, [toolId]: { ...d.matrix[toolId], [personaId]: level } } }));

  const setRow = (toolId: string, level: BoardToolLevel) =>
    setDraft((d) => ({
      ...d,
      matrix: { ...d.matrix, [toolId]: Object.fromEntries(members.map((m) => [m.id, level])) },
    }));

  const setCap = (key: keyof BoardSpendCaps, raw: string) => {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return;
    const ceiling = key === "metaAdsDailyUsd" ? 500 : 2000;
    setDraft((d) => ({
      ...d,
      spendCaps: { ...d.spendCaps, [key]: Math.min(Math.max(0, parsed), ceiling) },
    }));
  };

  return (
    <AdminEditorSection
      title="Tools & permissions"
      description="What each board member may look up or change while chatting or in meetings. Every call is logged; writes at the Propose level wait for your approval."
      footer={
        <>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!isDirty || isSaving || invalidAllowEntries.length > 0 || tooManyAllowEntries}
            onClick={() => onSave({ ...draft, allowList: draftAllowList })}
          >
            {isSaving ? "Saving…" : "Save permissions"}
          </button>
          <button
            type="button"
            className="btn btn-outline-secondary"
            disabled={isSaving || (JSON.stringify(draft) === JSON.stringify(defaults) && draftAllowList.length === 0)}
            onClick={() => {
              setDraft(defaults);
              setAllowListText("");
            }}
          >
            Reset to defaults
          </button>
          {errorMessage ? <span className="small text-danger">{errorMessage}</span> : null}
        </>
      }
    >
      {envDisabled ? (
        <div className="alert alert-warning py-2 small">
          <i className="bi bi-exclamation-triangle me-1" aria-hidden="true" />
          Tools are switched off at the stack level (<code>BoardToolsEnabled=false</code>). Settings here are kept
          but no member can call anything until that parameter is set back to <code>true</code>.
        </div>
      ) : null}

      <div className="row g-4 mb-3">
        <div className="col-12 col-lg-4">
          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-tools-enabled"
              checked={draft.enabled}
              onChange={(ev) => setDraft((d) => ({ ...d, enabled: ev.target.checked }))}
            />
            <label className="form-check-label fw-semibold" htmlFor="board-tools-enabled">
              Tools enabled
            </label>
          </div>
          <div className="form-text">Kill switch. Off means every member answers from the context pack only.</div>
        </div>
        <div className="col-12 col-lg-8">
          <label className="form-label small fw-semibold mb-1" htmlFor="board-tools-global-mode">
            Global mode
          </label>
          <select
            id="board-tools-global-mode"
            className="form-select form-select-sm admin-tools-global-mode"
            value={draft.globalMode}
            onChange={(ev) => setDraft((d) => ({ ...d, globalMode: ev.target.value as BoardToolGlobalMode }))}
          >
            {BOARD_TOOL_GLOBAL_MODES.map((m) => (
              <option key={m} value={m}>{TOOL_GLOBAL_MODE_LABELS[m]}</option>
            ))}
          </select>
          <div className="form-text">
            A ceiling over the whole matrix: <strong>Read-only</strong> makes every member read-only whatever the
            cells say; <strong>Propose</strong> turns Act cells into Propose; <strong>Act</strong> lets the cells
            apply as set.
          </div>
        </div>
      </div>

      <div className="d-flex flex-wrap gap-3 small text-muted mb-2">
        {(Object.keys(TOOL_LEVEL_LABELS) as BoardToolLevel[]).map((lvl) => (
          <span key={lvl}>
            <span className={`badge ${TOOL_LEVEL_BADGE_CLASS[lvl]} me-1`}>{TOOL_LEVEL_LABELS[lvl]}</span>
            {TOOL_LEVEL_HELP[lvl]}
          </span>
        ))}
      </div>

      <div className="table-responsive">
        <table className="table table-sm align-middle board-tools-matrix mb-2">
          <thead>
            <tr>
              <th scope="col">Tool</th>
              {members.map((m) => (
                <th scope="col" key={m.id} className="text-center small" title={memberLabel(members, m.id)}>
                  {m.shortName}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {registry.map((tool) => {
              const levels = levelsUpTo(tool.maxLevel);
              const writeOps = tool.operations.filter((op) => op.kind === "write");
              const readOps = tool.operations.filter((op) => op.kind === "read");
              const needsToken = tool.id === "github" && !repoWriteEnabled;
              return (
                <tr key={tool.id}>
                  <td>
                    <div className="fw-semibold">{tool.label}</div>
                    <div className="small text-muted">{tool.description}</div>
                    <details className="small mt-1">
                      <summary className="text-muted">
                        {readOps.length} read · {writeOps.length} write operation{writeOps.length === 1 ? "" : "s"}
                      </summary>
                      <ul className="mb-0 ps-3 mt-1">
                        {tool.operations.map((op) => (
                          <li key={op.name}>
                            <code>{op.name}</code>
                            {op.kind === "write" ? <span className="badge text-bg-warning ms-1">write</span> : null}
                            <span className="text-muted"> — {op.description}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                    {needsToken ? (
                      <div className="small text-warning mt-1">
                        <i className="bi bi-key me-1" aria-hidden="true" />
                        Writes and security alerts need a real PAT in{" "}
                        <code>lxsoftware-admin-siutindei-board-github-token</code>; reads work without it.
                      </div>
                    ) : null}
                    {tool.id === "mail" ? (
                      mailSendEnabled ? (
                        <div className="small text-muted mt-1">
                          <i className="bi bi-send-check me-1" aria-hidden="true" />
                          Sends from <code>*@{mailDomain}</code>. <strong>Act</strong> only sends to the allow-list
                          below; everyone else goes to Approvals.
                        </div>
                      ) : (
                        <div className="small text-warning mt-1">
                          <i className="bi bi-send-slash me-1" aria-hidden="true" />
                          Sending is off (<code>BoardMailSendingEnabled=false</code>): writes are drafted for you but
                          cannot be sent until the domain is verified in SES.
                        </div>
                      )
                    ) : null}
                    {tool.id === "research" ? (
                      searchConfigured ? (
                        <div className="small text-muted mt-1">Results are cached for 24 hours.</div>
                      ) : (
                        <div className="small text-warning mt-1">
                          No Brave Search key in <code>lxsoftware-admin-siutindei-board-search-api-key</code>. Queries
                          fail until one is set (or OpenRouter <code>:online</code> is used as a
                          fallback).
                        </div>
                      )
                    ) : null}
                    {tool.id === "meta" ? (
                      metaConfigured ? (
                        <div className="small text-muted mt-1">
                          Webhook at <code>/webhooks/meta/siutindei</code>{" "}
                          (<code>/webhooks/meta</code> still works). WhatsApp{" "}
                          <strong>act</strong> only inside the 24-hour window, to the allow-list.
                          Ads <strong>act</strong> only while daily and monthly caps have room;
                          otherwise <code>create_ad_set</code> / <code>boost_post</code> go to
                          Approvals.
                        </div>
                      ) : (
                        <div className="small text-warning mt-1">
                          Put a real System User token in{" "}
                          <code>lxsoftware-admin-siutindei-board-meta-token</code> and set the Page / WhatsApp
                          ids. Enable coexistence so the owner&apos;s phone keeps the number.
                        </div>
                      )
                    ) : null}
                    {tool.id === "stores" ? (
                      storesConfigured ? (
                        <div className="small text-muted mt-1">
                          Daily metrics refresh hourly. The CMO may <strong>act</strong> on a review
                          reply; release notes always go to Approvals.
                        </div>
                      ) : (
                        <div className="small text-warning mt-1">
                          Replace the dummy JSON in{" "}
                          <code>lxsoftware-admin-siutindei-board-app-store-connect-key</code> and{" "}
                          <code>lxsoftware-admin-siutindei-board-google-play-sa</code> (keys already exist). JWT for
                          App Store Connect is signed in the Lambda.
                        </div>
                      )
                    ) : null}
                    {tool.id === "web" ? (
                      webConfigured ? (
                        <div className="small text-muted mt-1">
                          GA4 and GTM reads refresh hourly. Several properties and containers are
                          supported. Publish and Google Ads are later milestones.
                        </div>
                      ) : (
                        <div className="small text-warning mt-1">
                          Replace the dummy JSON in{" "}
                          <code>lxsoftware-admin-siutindei-board-google-analytics-sa</code> (dedicated SA, not the
                          Play key), then set <code>Ga4PropertyIds</code> and{" "}
                          <code>GtmContainers</code> (<code>account:container</code> pairs).
                        </div>
                      )
                    ) : null}
                    {tool.id === "finance" || tool.id === "product" ? (
                      dataApiConfigured ? (
                        <div className="small text-muted mt-1">
                          Reads the siutindei Aurora database through the RDS Data API.
                        </div>
                      ) : (
                        <div className="small text-warning mt-1">
                          Data API is off until <code>SiutindeiClusterArn</code> and{" "}
                          <code>SiutindeiDbSecretArn</code> are set and{" "}
                          <code>scripts/siutindei/receivables.sql</code> is applied.
                        </div>
                      )
                    ) : null}
                    <div className="small mt-1 d-flex gap-2 flex-wrap">
                      <span className="text-muted">Set all:</span>
                      {levels.map((lvl) => (
                        <button
                          key={lvl}
                          type="button"
                          className="btn btn-link btn-sm p-0 align-baseline"
                          onClick={() => setRow(tool.id, lvl)}
                        >
                          {TOOL_LEVEL_LABELS[lvl]}
                        </button>
                      ))}
                    </div>
                  </td>
                  {members.map((m) => {
                    const configured = draft.matrix[tool.id]?.[m.id] ?? "off";
                    const effective = effectiveToolLevel(draft, tool.id, m.id);
                    const isCapped = effective !== configured;
                    return (
                      <td key={m.id} className="text-center">
                        <select
                          className={`form-select form-select-sm board-tools-cell board-tools-cell-${configured}`}
                          aria-label={`${tool.label} access for ${memberLabel(members, m.id)}`}
                          value={configured}
                          onChange={(ev) => setCell(tool.id, m.id, ev.target.value as BoardToolLevel)}
                        >
                          {levels.map((lvl) => (
                            <option key={lvl} value={lvl}>{TOOL_LEVEL_LABELS[lvl]}</option>
                          ))}
                        </select>
                        {isCapped ? (
                          <div className="small text-muted" title="Capped by the global mode or kill switch">
                            → {TOOL_LEVEL_LABELS[effective]}
                          </div>
                        ) : null}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="row g-3 mt-1">
        <div className="col-12 col-lg-6">
          <label className="form-label small fw-semibold mb-1" htmlFor="board-mail-allow-list">
            Recipient allow-list <span className="text-muted fw-normal">({draftAllowList.length}/{BOARD_MAIL_ALLOW_LIST_MAX_ENTRIES})</span>
          </label>
          <textarea
            id="board-mail-allow-list"
            className={`form-control form-control-sm font-monospace ${invalidAllowEntries.length > 0 || tooManyAllowEntries ? "is-invalid" : ""}`}
            rows={4}
            value={allowListText}
            placeholder={"coach@swimhk.example\n@trusted-vendor.example\n+85291234567"}
            spellCheck={false}
            onChange={(ev) => setAllowListText(ev.target.value)}
          />
          {invalidAllowEntries.length > 0 ? (
            <div className="invalid-feedback d-block">
              Not an address, @domain, or phone: {invalidAllowEntries.slice(0, 3).join(", ")}
            </div>
          ) : tooManyAllowEntries ? (
            <div className="invalid-feedback d-block">At most {BOARD_MAIL_ALLOW_LIST_MAX_ENTRIES} entries.</div>
          ) : null}
          <div className="form-text">
            One per line: a full address, <code>@domain</code>, or an E.164 / 8–15 digit phone.
            Members with <strong>Act</strong> on Email or WhatsApp send to these recipients directly
            (logged); anyone else — every parent, by design — always comes to you first.
            Your own <code>@{mailDomain}</code> mailboxes are always allowed.
          </div>
        </div>
        <div className="col-12 col-lg-6">
          <div className="small fw-semibold mb-1">Meta ads spend caps</div>
          <div className="row g-2">
            <div className="col-6">
              <label className="form-label small mb-1" htmlFor="board-ads-daily-cap">
                Daily (USD)
              </label>
              <input
                id="board-ads-daily-cap"
                type="number"
                className="form-control form-control-sm"
                min={0}
                max={500}
                step={1}
                value={draft.spendCaps.metaAdsDailyUsd}
                onChange={(ev) => setCap("metaAdsDailyUsd", ev.target.value)}
              />
            </div>
            <div className="col-6">
              <label className="form-label small mb-1" htmlFor="board-ads-monthly-cap">
                Monthly (USD)
              </label>
              <input
                id="board-ads-monthly-cap"
                type="number"
                className="form-control form-control-sm"
                min={0}
                max={2000}
                step={1}
                value={draft.spendCaps.metaAdsMonthlyUsd}
                onChange={(ev) => setCap("metaAdsMonthlyUsd", ev.target.value)}
              />
            </div>
          </div>
          <div className="form-text">
            Hitting either cap turns <code>create_ad_set</code> and <code>boost_post</code> into
            Approvals. Clamped to USD 500 / day and USD 2,000 / month.
          </div>
          {adsSpend ? (
            <div className="small mt-2">
              Today {formatUsageCost(adsSpend.dailyUsd)} of {formatUsageCost(adsSpend.dailyCapUsd)}.
              This month {formatUsageCost(adsSpend.monthlyUsd)} of {formatUsageCost(adsSpend.monthlyCapUsd)}
              {adsSpend.graphMonthlyUsd > 0
                ? ` (Meta reports ${formatUsageCost(adsSpend.graphMonthlyUsd)}).`
                : "."}
            </div>
          ) : null}
        </div>
      </div>

      <div className="form-check form-switch small mt-3">
        <input
          className="form-check-input"
          type="checkbox"
          id="board-tools-show-log"
          checked={showCallLog}
          onChange={(ev) => onToggleCallLog(ev.target.checked)}
        />
        <label className="form-check-label" htmlFor="board-tools-show-log">
          Show the tool call log
        </label>
      </div>
      {showCallLog ? (
        isCallLogLoading ? (
          <div className="small text-muted mt-2">Loading…</div>
        ) : !callLog || callLog.length === 0 ? (
          <div className="small text-muted mt-2">No tool calls yet.</div>
        ) : (
          <ul className="list-group list-group-flush mt-2 small">
            {callLog.map((c) => (
              <li key={c.callId} className="list-group-item px-0 py-2">
                <div className="d-flex flex-wrap gap-2 text-muted mb-1">
                  <span className="fw-semibold text-body">{c.displayName}</span>
                  <span>
                    <DateTimeDisplay iso={c.createdAt} />
                  </span>
                  <span className={`badge ${TOOL_LEVEL_BADGE_CLASS[c.level] ?? "text-bg-light border"}`}>{TOOL_LEVEL_LABELS[c.level] ?? c.level}</span>
                  <span>{c.context.kind === "meeting" ? "meeting" : c.actor === "owner" ? "approved by you" : "chat"}</span>
                  <span>{c.durationMs} ms</span>
                </div>
                <BoardToolCallList calls={[c]} />
                {c.resultPreview ? (
                  <details className="mt-1">
                    <summary className="text-muted">result</summary>
                    <pre className="small bg-light border rounded p-2 mb-0 mt-1 board-tool-result">
                      {c.resultPreview}
                    </pre>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        )
      ) : null}
    </AdminEditorSection>
  );
}
