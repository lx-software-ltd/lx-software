import { useEffect, useState, type FormEvent } from "react";
import { useResume } from "../../hooks/useResume";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import { assertJobDone } from "../../lib/pollJob";
import {
  DOCX_TYPE,
  contentTypeForFile,
  readFileBase64,
  tailorProgress,
} from "../../lib/resumeModel";
import { AdminEditorSection, AdminField, AdminFieldGrid } from "../ui";

export function ResumeTailorSection({
  enabled,
  templateResumeId,
  onOpenResume,
  onSectionDirty,
}: {
  readonly enabled: boolean;
  readonly templateResumeId: string;
  readonly onOpenResume: (id: string) => void;
  readonly onSectionDirty?: (dirty: boolean) => void;
}) {
  const resume = useResume();
  const resumes = (resume.resumes.data?.items ?? []).filter((row) => row.format === "docx" && row.extract.status === "ready");
  const postings = resume.postings.data?.items ?? [];
  const [sourceChoice, setSourceChoice] = useState<"template" | "upload" | null>(null);
  const [templateChoice, setTemplateChoice] = useState<string | null>(null);
  const source = sourceChoice ?? (templateResumeId ? "template" : "upload");
  const templateId = templateChoice ?? templateResumeId;
  const [file, setFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState("");
  const [postingId, setPostingId] = useState("");
  const [company, setCompany] = useState("");
  const [position, setPosition] = useState("");
  const [adText, setAdText] = useState("");
  const [addToTracker, setAddToTracker] = useState(true);
  const dirty = Boolean(
    sourceChoice ||
      templateChoice ||
      file ||
      uploadTitle.trim() ||
      company.trim() ||
      position.trim() ||
      adText.trim() ||
      postingId ||
      !addToTracker,
  );

  useEffect(() => {
    onSectionDirty?.(dirty);
    return () => onSectionDirty?.(false);
  }, [dirty, onSectionDirty]);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState<string | null>(null);
  const busy = resume.upload.isPending || resume.tailor.isPending;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!enabled) return;
    setError(null);
    try {
      let chosen = source === "template" ? templateId || templateResumeId : "";
      if (source === "upload") {
        if (!file) throw new Error("Choose a Word document.");
        const contentType = contentTypeForFile(file.name, file.type);
        if (contentType !== DOCX_TYPE) throw new Error("Only a .docx Word document can be the template.");
        setProgress("Reading the resume…");
        const dataBase64 = await readFileBase64(file);
        const uploaded = await resume.upload.mutateAsync({
          title: uploadTitle,
          contentType,
          dataBase64,
          makeTemplate: true,
        });
        assertJobDone(uploaded.job);
        chosen = uploaded.resume.id;
      }
      if (!chosen) throw new Error("Choose a template resume.");
      setProgress(tailorProgress("queued"));
      const job = await resume.tailor.mutateAsync({
        templateId: chosen,
        postingId: postingId || undefined,
        posting: postingId ? undefined : { title: position, company, adText },
        addToTracker,
        onStatus: (status) => setProgress(tailorProgress(status)),
      });
      const resumeId = job.resumeIds[0];
      if (!resumeId) throw new Error("The tailored resume was not saved.");
      onSectionDirty?.(false);
      onOpenResume(resumeId);
    } catch (caught) {
      setProgress("");
      setError(caught instanceof Error ? caught.message : getAdminApiErrorMessage(caught) ?? "Could not tailor the resume.");
    }
  }

  return (
    <AdminEditorSection
      title="New resume"
      description="Rewrite the allowed paragraphs of a Word template for one job post. The template file is not changed."
      footer={
        <button type="submit" form="resume-tailor" className="btn btn-primary" disabled={!enabled || busy}>
          {busy ? "Generating…" : "Generate"}
        </button>
      }
    >
      <form id="resume-tailor" onSubmit={(event) => void onSubmit(event)}>
        {error ? (
          <div className="alert alert-danger py-2 small" role="alert">
            {error}
          </div>
        ) : null}
        {progress ? <p className="small text-muted">{progress}</p> : null}
        <AdminFieldGrid columns={1}>
          <AdminField label="Template" htmlFor="resume-tailor-source">
            <select
              id="resume-tailor-source"
              className="form-select"
              value={source}
              onChange={(event) => setSourceChoice(event.target.value as "template" | "upload")}
            >
              <option value="template">Current template</option>
              <option value="upload">Upload a new Word document</option>
            </select>
          </AdminField>
          {source === "template" ? (
            <AdminField label="Word template" htmlFor="resume-tailor-template">
              <select
                id="resume-tailor-template"
                className="form-select"
                value={templateId || templateResumeId}
                onChange={(event) => setTemplateChoice(event.target.value)}
              >
                <option value="">Choose a template</option>
                {resumes.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.title}
                  </option>
                ))}
              </select>
            </AdminField>
          ) : (
            <>
              <AdminField label="Title" htmlFor="resume-tailor-title">
                <input
                  id="resume-tailor-title"
                  className="form-control"
                  value={uploadTitle}
                  onChange={(event) => setUploadTitle(event.target.value)}
                />
              </AdminField>
              <AdminField label="Word file" htmlFor="resume-tailor-file">
                <input
                  id="resume-tailor-file"
                  className="form-control"
                  type="file"
                  accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
              </AdminField>
            </>
          )}
          <AdminField label="Saved job post" htmlFor="resume-tailor-posting">
            <select
              id="resume-tailor-posting"
              className="form-select"
              value={postingId}
              onChange={(event) => setPostingId(event.target.value)}
            >
              <option value="">Paste a new job post</option>
              {postings.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.company} — {row.title}
                </option>
              ))}
            </select>
          </AdminField>
          {postingId ? null : (
            <>
              <AdminField label="Company" htmlFor="resume-tailor-company">
                <input
                  id="resume-tailor-company"
                  className="form-control"
                  value={company}
                  onChange={(event) => setCompany(event.target.value)}
                />
              </AdminField>
              <AdminField label="Position" htmlFor="resume-tailor-position">
                <input
                  id="resume-tailor-position"
                  className="form-control"
                  value={position}
                  onChange={(event) => setPosition(event.target.value)}
                />
              </AdminField>
              <AdminField label="Job post" htmlFor="resume-tailor-ad">
                <textarea
                  id="resume-tailor-ad"
                  className="form-control"
                  rows={6}
                  value={adText}
                  onChange={(event) => setAdText(event.target.value)}
                />
              </AdminField>
            </>
          )}
          <AdminField label="Tracker" htmlFor="resume-tailor-track">
            <div className="form-check">
              <input
                id="resume-tailor-track"
                className="form-check-input"
                type="checkbox"
                checked={addToTracker}
                onChange={(event) => setAddToTracker(event.target.checked)}
              />
              <label className="form-check-label" htmlFor="resume-tailor-track">
                Add to job tracker
              </label>
            </div>
          </AdminField>
        </AdminFieldGrid>
      </form>
    </AdminEditorSection>
  );
}
