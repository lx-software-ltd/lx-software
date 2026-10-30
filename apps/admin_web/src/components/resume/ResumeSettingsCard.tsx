import { useEffect, useState } from "react";
import { useResume } from "../../hooks/useResume";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import {
  BULLET_POLICIES,
  LOCKED_FACTS,
  OUTPUT_LENGTHS,
  PAGE_SIZES,
  REWRITE_SCOPE,
  type ResumeOverview,
  type ResumeSettings,
  type RewriteScope,
} from "../../lib/resumeModel";
import { AdminEditorSection, AdminField, AdminFieldGrid } from "../ui";

export function ResumeSettingsCard({
  overview,
  enabled,
  onSectionDirty,
}: {
  readonly overview: ResumeOverview;
  readonly enabled: boolean;
  readonly onSectionDirty?: (dirty: boolean) => void;
}) {
  const resume = useResume();
  const [settings, setSettings] = useState<ResumeSettings>(overview.settings);
  const formId = "resume-settings";
  const spend = overview.spendUsdMonth.toFixed(2);
  const scopeMissing = settings.rewriteScope.length === 0;
  const dirty = JSON.stringify(settings) !== JSON.stringify(overview.settings);

  useEffect(() => {
    onSectionDirty?.(dirty);
    return () => onSectionDirty?.(false);
  }, [dirty, onSectionDirty]);

  function toggleScope(scope: RewriteScope) {
    const has = settings.rewriteScope.includes(scope);
    setSettings({
      ...settings,
      rewriteScope: has ? settings.rewriteScope.filter((item) => item !== scope) : [...settings.rewriteScope, scope],
    });
  }

  return (
    <AdminEditorSection
      title="Generation"
      description={LOCKED_FACTS}
      footer={
        <button
          type="submit"
          form={formId}
          className="btn btn-primary"
          disabled={!enabled || scopeMissing || resume.saveSettings.isPending}
        >
          {resume.saveSettings.isPending ? "Saving…" : "Save"}
        </button>
      }
    >
      <form
        id={formId}
        onSubmit={(event) => {
          event.preventDefault();
          if (!enabled || scopeMissing) return;
          void resume.saveSettings.mutateAsync(settings).then((saved) => setSettings(saved.settings));
        }}
      >
        {scopeMissing ? (
          <div className="alert alert-danger py-2 small" role="alert">
            Choose at least one part of the resume to rewrite.
          </div>
        ) : null}
        {resume.saveSettings.isError ? (
          <div className="alert alert-danger py-2 small" role="alert">
            {getAdminApiErrorMessage(resume.saveSettings.error) ?? "Could not save settings."}
          </div>
        ) : null}
        <p className="small text-muted">
          Spent US$ {spend} of {settings.maxUsdPerMonth.toFixed(2)} this month.
          {overview.defaultModel ? ` Default model ${overview.defaultModel}.` : ""}
          {overview.pdfCjk ? " PDF can include Chinese." : " PDF export is Latin-only for now."}
        </p>
        <AdminFieldGrid columns={2}>
          <AdminField label="Model" htmlFor="resume-model">
            <input
              id="resume-model"
              className="form-control"
              value={settings.model}
              placeholder={overview.defaultModel || "OpenRouter model"}
              onChange={(event) => setSettings({ ...settings, model: event.target.value })}
            />
          </AdminField>
          <AdminField label="Monthly cap (USD)" htmlFor="resume-cap">
            <input
              id="resume-cap"
              className="form-control"
              type="number"
              min={0}
              max={1000}
              step="0.01"
              value={settings.maxUsdPerMonth}
              onChange={(event) => setSettings({ ...settings, maxUsdPerMonth: Number(event.target.value) })}
            />
          </AdminField>
          <AdminField label="Temperature" htmlFor="resume-temperature">
            <input
              id="resume-temperature"
              className="form-control"
              type="number"
              min={0}
              max={1}
              step="0.1"
              value={settings.temperature}
              onChange={(event) => setSettings({ ...settings, temperature: Number(event.target.value) })}
            />
          </AdminField>
          <AdminField label="Output length" htmlFor="resume-length">
            <select
              id="resume-length"
              className="form-select"
              value={settings.outputLength}
              onChange={(event) =>
                setSettings({ ...settings, outputLength: event.target.value as ResumeSettings["outputLength"] })
              }
            >
              {OUTPUT_LENGTHS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </AdminField>
          <AdminField label="Bullet policy" htmlFor="resume-bullets">
            <select
              id="resume-bullets"
              className="form-select"
              value={settings.bulletPolicy}
              onChange={(event) =>
                setSettings({ ...settings, bulletPolicy: event.target.value as ResumeSettings["bulletPolicy"] })
              }
            >
              {BULLET_POLICIES.map((value) => (
                <option key={value} value={value}>
                  {value === "keep" ? "Keep the bullet count" : "Allow one bullet more or less"}
                </option>
              ))}
            </select>
          </AdminField>
          <AdminField label="Page size" htmlFor="resume-page">
            <select
              id="resume-page"
              className="form-select"
              value={settings.pageSize}
              onChange={(event) => setSettings({ ...settings, pageSize: event.target.value as ResumeSettings["pageSize"] })}
            >
              {PAGE_SIZES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </AdminField>
          <AdminField label="Rewrite scope" span={2}>
            <div className="d-flex flex-wrap gap-3">
              {REWRITE_SCOPE.map((scope) => (
                <div className="form-check" key={scope}>
                  <input
                    id={`resume-scope-${scope}`}
                    className="form-check-input"
                    type="checkbox"
                    checked={settings.rewriteScope.includes(scope)}
                    onChange={() => toggleScope(scope)}
                  />
                  <label className="form-check-label" htmlFor={`resume-scope-${scope}`}>
                    {scope}
                  </label>
                </div>
              ))}
            </div>
          </AdminField>
          <AdminField label="New skills" htmlFor="resume-skills" span={2}>
            <div className="form-check">
              <input
                id="resume-skills"
                className="form-check-input"
                type="checkbox"
                checked={settings.allowNewSkills}
                onChange={(event) => setSettings({ ...settings, allowNewSkills: event.target.checked })}
              />
              <label className="form-check-label" htmlFor="resume-skills">
                Allow new skills. They are listed on the resume for you to confirm.
              </label>
            </div>
          </AdminField>
          <AdminField label="Extra instructions" htmlFor="resume-instructions" span={2}>
            <textarea
              id="resume-instructions"
              className="form-control"
              rows={4}
              maxLength={4000}
              value={settings.instructions}
              onChange={(event) => setSettings({ ...settings, instructions: event.target.value })}
            />
          </AdminField>
        </AdminFieldGrid>
      </form>
    </AdminEditorSection>
  );
}
