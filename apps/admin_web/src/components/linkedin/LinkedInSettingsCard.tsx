import { useState } from "react";
import { useLinkedIn } from "../../hooks/useLinkedIn";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import {
  BUILTIN_FORBIDDEN,
  WEEKDAY_OPTIONS,
  pillarLabel,
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
        <p className="mb-1">Profile posting is not connected.</p>
        <p className="text-muted small mb-0">
          Approved posts open in the LinkedIn share box. You post them yourself, then mark them posted.
          {overview.publishEnabled ? " Direct publishing is switched on, and still waits for the LinkedIn API step." : ""}
        </p>
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
            <AdminField label="Notify" htmlFor="linkedin-notify" span={2}>
              <input
                id="linkedin-notify"
                className="form-control"
                type="email"
                value={settings.notifyEmail}
                placeholder="you@example.com"
                onChange={(event) => setSettings({ ...settings, notifyEmail: event.target.value })}
              />
            </AdminField>
            <AdminField label="Voice" htmlFor="linkedin-voice" span={2}>
              <textarea
                id="linkedin-voice"
                className="form-control"
                rows={3}
                maxLength={1000}
                value={settings.voiceNotes}
                onChange={(event) => setSettings({ ...settings, voiceNotes: event.target.value })}
              />
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
