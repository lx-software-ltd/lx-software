import { useState } from "react";
import { useLinkedIn } from "../../hooks/useLinkedIn";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import { formatDateTimeHKT } from "../../lib/formatDisplay";
import {
  BUILTIN_FORBIDDEN,
  STYLE_EXAMPLE_MAX,
  WEEKDAY_OPTIONS,
  linkedInAccessState,
  pillarLabel,
  type LinkedInConnection,
  type LinkedInOverview,
  type LinkedInDraftSettings,
} from "../../lib/linkedinModel";
import { AdminEditorSection, AdminField, AdminFieldGrid } from "../ui";

export function LinkedInSettingsCard({
  overview,
  enabled,
}: {
  readonly overview: LinkedInOverview;
  readonly enabled: boolean;
}) {
  const linkedIn = useLinkedIn();
  const [settings, setSettings] = useState<LinkedInDraftSettings>(overview.settings);
  const [extraWords, setExtraWords] = useState(overview.settings.forbiddenWords.join("\n"));
  const formId = "linkedin-settings";
  const spend = overview.spendUsdMonth.toFixed(2);

  return (
    <div className="d-flex flex-column gap-3">
      <AdminEditorSection title="Connection">
        <LinkedInConnectionPanel overview={overview} enabled={enabled} />
      </AdminEditorSection>
      <AdminEditorSection
        title="Drafts"
        footer={
          <button type="submit" form={formId} className="btn btn-primary" disabled={!enabled || linkedIn.saveSettings.isPending}>
            {linkedIn.saveSettings.isPending ? "Saving…" : "Save"}
          </button>
        }
      >
        <form
          id={formId}
          onSubmit={(event) => {
            event.preventDefault();
            if (!enabled) return;
            const forbiddenWords = extraWords
              .split("\n")
              .map((word) => word.trim().toLowerCase())
              .filter(Boolean);
            void linkedIn.saveSettings
              .mutateAsync({ ...settings, forbiddenWords })
              .then((saved) => {
                setSettings(saved.settings);
                setExtraWords(saved.settings.forbiddenWords.join("\n"));
              })
              .catch(() => undefined);
          }}
        >
          {linkedIn.saveSettings.isError ? (
            <div className="alert alert-danger py-2 small" role="alert">
              {getAdminApiErrorMessage(linkedIn.saveSettings.error) ?? "Could not save settings."}
            </div>
          ) : null}
          <AdminFieldGrid columns={2}>
            <AdminField label="Posts per week" htmlFor="linkedin-per-week">
              <input
                id="linkedin-per-week"
                className="form-control"
                type="number"
                min={1}
                max={7}
                value={settings.postsPerWeek}
                onChange={(event) => setSettings({ ...settings, postsPerWeek: Number(event.target.value) })}
              />
            </AdminField>
            <AdminField label="Drafts each Sunday" htmlFor="linkedin-batch">
              <input
                id="linkedin-batch"
                className="form-control"
                type="number"
                min={1}
                max={6}
                value={settings.draftsPerGeneration}
                onChange={(event) => setSettings({ ...settings, draftsPerGeneration: Number(event.target.value) })}
              />
            </AdminField>
            <AdminField label="Slot hour (HKT)" htmlFor="linkedin-hour">
              <input
                id="linkedin-hour"
                className="form-control"
                type="number"
                min={0}
                max={23}
                value={settings.slotHour}
                onChange={(event) => setSettings({ ...settings, slotHour: Number(event.target.value) })}
              />
            </AdminField>
            <AdminField label="Slot minute" htmlFor="linkedin-minute">
              <input
                id="linkedin-minute"
                className="form-control"
                type="number"
                min={0}
                max={59}
                value={settings.slotMinute}
                onChange={(event) => setSettings({ ...settings, slotMinute: Number(event.target.value) })}
              />
            </AdminField>
            <AdminField label="Hashtag cap" htmlFor="linkedin-cap">
              <input
                id="linkedin-cap"
                className="form-control"
                type="number"
                min={0}
                max={5}
                value={settings.hashtagCap}
                onChange={(event) => setSettings({ ...settings, hashtagCap: Number(event.target.value) })}
              />
            </AdminField>
            <AdminField label="Monthly draft budget (USD)" htmlFor="linkedin-budget">
              <input
                id="linkedin-budget"
                className="form-control"
                type="number"
                min={0}
                max={50}
                step="0.5"
                value={settings.maxUsdPerMonth}
                onChange={(event) => setSettings({ ...settings, maxUsdPerMonth: Number(event.target.value) })}
              />
            </AdminField>
            <AdminField label="Notify" htmlFor="linkedin-notify">
              <input
                id="linkedin-notify"
                className="form-control"
                type="email"
                value={settings.notifyEmail}
                placeholder="you@example.com"
                onChange={(event) => setSettings({ ...settings, notifyEmail: event.target.value })}
              />
            </AdminField>
            <AdminField label="Model" htmlFor="linkedin-model">
              <input
                id="linkedin-model"
                className="form-control"
                value={settings.model}
                placeholder={overview.defaultModel || "provider/model"}
                spellCheck={false}
                autoComplete="off"
                onChange={(event) => setSettings({ ...settings, model: event.target.value })}
              />
            </AdminField>
            <AdminField label="Voice" htmlFor="linkedin-voice" span={2}>
              <textarea
                id="linkedin-voice"
                className="form-control"
                rows={3}
                maxLength={1000}
                placeholder="Short sentences. Concrete. No slogans."
                value={settings.voiceNotes}
                onChange={(event) => setSettings({ ...settings, voiceNotes: event.target.value })}
              />
              <p className="form-text mb-0">
                How the posts should sound. This overrides the default tone. Substance and safety rules still apply:
                written as I, not we; one real situation told in order with its specifics; no sensationalism, buzzwords
                or emoji; no employer, no availability, and the blocked phrases. Leave blank for the default tone: first
                person, short lines, and a closing question. When Ideas is empty, drafts draw on a built-in bank of
                concrete engineering situations.
              </p>
              {overview.recommendedVoice && settings.voiceNotes.trim() !== overview.recommendedVoice ? (
                <button
                  type="button"
                  className="btn btn-link btn-sm px-0 mt-1"
                  onClick={() => setSettings({ ...settings, voiceNotes: overview.recommendedVoice ?? "" })}
                >
                  Use recommended voice
                </button>
              ) : null}
            </AdminField>
            <AdminField label="Example post" htmlFor="linkedin-example" span={2}>
              <textarea
                id="linkedin-example"
                className="form-control"
                rows={6}
                maxLength={overview.styleExampleMax ?? STYLE_EXAMPLE_MAX}
                placeholder="Paste a post you wrote and liked."
                value={settings.styleExample}
                onChange={(event) => setSettings({ ...settings, styleExample: event.target.value })}
              />
              <p className="form-text mb-0">
                A post in your own words, shown to the model as the tone to match: its pacing, paragraph length,
                hedging, and ending. The subject, opening line, and sentences are not reused. Replace it with a newer
                post when your writing moves on, or leave blank to send no example.
              </p>
            </AdminField>
            <AdminField label="Extra phrases to block" htmlFor="linkedin-blocked" span={2}>
              <textarea
                id="linkedin-blocked"
                className="form-control"
                rows={3}
                value={extraWords}
                onChange={(event) => setExtraWords(event.target.value)}
              />
              <p className="form-text mb-0">One phrase per line. Always blocked: {BUILTIN_FORBIDDEN.join(", ")}.</p>
            </AdminField>
          </AdminFieldGrid>
          <fieldset className="mt-3">
            <legend className="form-label small">Weekdays</legend>
            <div className="d-flex flex-wrap gap-3">
              {WEEKDAY_OPTIONS.map((day) => (
                <label key={day.id} className="form-check-label">
                  <input
                    className="form-check-input me-1"
                    type="checkbox"
                    checked={settings.weekdays.includes(day.id)}
                    onChange={(event) => {
                      const weekdays = event.target.checked
                        ? [...settings.weekdays, day.id].sort((a, b) => a - b)
                        : settings.weekdays.filter((value) => value !== day.id);
                      setSettings({ ...settings, weekdays });
                    }}
                  />
                  {day.label}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="mt-3">
            <legend className="form-label small">Pillars</legend>
            <div className="d-flex flex-column gap-1">
              {overview.pillars.map((row) => (
                <label key={row.id} className="form-check-label">
                  <input
                    className="form-check-input me-1"
                    type="checkbox"
                    checked={settings.pillars.includes(row.id)}
                    onChange={(event) => {
                      const pillars = event.target.checked
                        ? [...settings.pillars, row.id]
                        : settings.pillars.filter((value) => value !== row.id);
                      setSettings({ ...settings, pillars });
                    }}
                  />
                  {pillarLabel(row.id)}
                </label>
              ))}
            </div>
          </fieldset>
          <label className="form-check mt-3">
            <input
              className="form-check-input"
              type="checkbox"
              checked={settings.allowProductMentions}
              onChange={(event) => setSettings({ ...settings, allowProductMentions: event.target.checked })}
            />
            Allow product names
          </label>
          <p className="text-muted small mt-3 mb-0">Draft spend this month: US$ {spend}. New drafts are generated Sunday at 18:00 HKT.</p>
        </form>
      </AdminEditorSection>
    </div>
  );
}

function connectionCopy(connection: LinkedInConnection): string {
  if (connection.appStatus === "unreadable") {
    return "The LinkedIn app secret could not be read. Until then, use the share box.";
  }
  if (!connection.appConfigured) {
    return "The LinkedIn app secret is not filled in yet. Until then, use the share box.";
  }
  return "Connect LinkedIn to post approved drafts at the slot. Until then, use the share box.";
}

function accessCopy(iso: string): { tone: "muted" | "warning"; text: string } | null {
  const state = linkedInAccessState(iso);
  if (!state) return null;
  const when = formatDateTimeHKT(iso);
  if (state === "expired") return { tone: "warning", text: `LinkedIn access expired ${when}. Connect again before the next slot.` };
  if (state === "soon") return { tone: "warning", text: `LinkedIn access expires ${when}. Connect again before the next slot.` };
  return { tone: "muted", text: `Access until ${when}.` };
}

function LinkedInConnectionPanel({
  overview,
  enabled,
}: {
  readonly overview: LinkedInOverview;
  readonly enabled: boolean;
}) {
  const linkedIn = useLinkedIn();
  const [includePages, setIncludePages] = useState(false);
  const connection = overview.connection;
  const connected = connection.status === "connected";
  const access = connected ? accessCopy(connection.tokenExpiresAt) : null;
  const error =
    getAdminApiErrorMessage(linkedIn.connect.error) ??
    getAdminApiErrorMessage(linkedIn.disconnect.error) ??
    getAdminApiErrorMessage(linkedIn.saveConnection.error) ??
    getAdminApiErrorMessage(linkedIn.refreshOrganizations.error);

  function choose(channel: string, organizationId: string) {
    void linkedIn.saveConnection.mutate({ channel, organizationId });
  }

  return (
    <div>
      {error ? (
        <div className="alert alert-danger py-2 small" role="alert">
          {error}
        </div>
      ) : null}
      {connected ? (
        <p className="mb-2">
          Connected{connection.memberName ? ` as ${connection.memberName}` : ""}.
          {overview.publishEnabled
            ? " Approved posts go out at the slot."
            : " Automatic posting is off, so approved posts still use the share box."}
        </p>
      ) : (
        <p className="mb-2">{connectionCopy(connection)}</p>
      )}
      {access ? (
        <p className={access.tone === "warning" ? "text-warning small mb-2" : "text-muted small mb-2"} role="status">
          {access.text}
        </p>
      ) : null}
      {connected ? (
        <div className="d-flex flex-column gap-2 mb-3">
          <label className="form-check mb-0">
            <input
              className="form-check-input"
              type="radio"
              name="linkedin-channel"
              checked={connection.channel !== "page"}
              onChange={() => choose("profile", connection.organizationId)}
            />
            Profile
          </label>
          <label className="form-check mb-0">
            <input
              className="form-check-input"
              type="radio"
              name="linkedin-channel"
              checked={connection.channel === "page"}
              disabled={connection.organizations.length === 0}
              onChange={() => choose("page", connection.organizations[0]?.id ?? "")}
            />
            Company page
          </label>
          {connection.includeOrganizations ? (
            connection.organizations.length === 0 ? (
              <p className="text-muted small mb-0">
                No company pages were returned. Refresh after Community Management is approved, or if this member administers a page.
              </p>
            ) : null
          ) : (
            <p className="text-muted small mb-0">
              This connection is profile only. Disconnect and connect again with company pages included.
            </p>
          )}
          {connection.channel === "page" && connection.organizations.length > 0 ? (
            <select
              className="form-select"
              aria-label="Company page"
              value={connection.organizationId}
              onChange={(event) => choose("page", event.target.value)}
            >
              {connection.organizations.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          ) : null}
        </div>
      ) : (
        <div className="mb-3">
          <label className="form-check mb-0">
            <input
              className="form-check-input"
              type="checkbox"
              checked={includePages}
              aria-describedby="linkedin-pages-help"
              onChange={(event) => setIncludePages(event.target.checked)}
            />
            Include company pages
          </label>
          <p id="linkedin-pages-help" className="form-text mb-0">
            Posts can then go out as a page you administer. The LinkedIn app needs Community Management approval; without it, leave this off.
          </p>
        </div>
      )}
      <div className="d-flex gap-2">
        {connected ? (
          <>
            {connection.includeOrganizations ? (
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                disabled={!enabled || linkedIn.refreshOrganizations.isPending}
                onClick={() => void linkedIn.refreshOrganizations.mutate()}
              >
                {linkedIn.refreshOrganizations.isPending ? "Refreshing…" : "Refresh pages"}
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              disabled={!enabled || linkedIn.disconnect.isPending}
              onClick={() => void linkedIn.disconnect.mutate()}
            >
              Disconnect
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={!enabled || !connection.appConfigured || linkedIn.connect.isPending}
            onClick={() => {
              void linkedIn.connect.mutateAsync(includePages).then((result) => {
                window.location.assign(result.url);
              });
            }}
          >
            Connect
          </button>
        )}
      </div>
    </div>
  );
}
