import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchResumeFile, useResume, useResumeDetail } from "../../hooks/useResume";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import { downloadBase64, openPreview, showPreview } from "../../lib/downloadBase64";
import { DRAFT_RECORD_ID } from "../../lib/expandedRecord";
import {
  contentTypeForFile,
  kindLabel,
  readFileBase64,
  type ResumeSummary,
} from "../../lib/resumeModel";
import {
  AdminCell,
  AdminCreateButton,
  AdminDataTable,
  AdminDataTableEmptyRow,
  AdminEditorPanel,
  AdminExpandableRow,
  AdminField,
  AdminFieldGrid,
  AdminFilterBar,
  AdminFilterField,
  AdminRecordTable,
  AdminRowActions,
  ConfirmDialog,
} from "../ui";
import { ResumeTemplateMap } from "./ResumeTemplateMap";

const NO_RESUMES: ResumeSummary[] = [];

const COLUMNS = [
  { key: "title", header: "Title" },
  { key: "kind", header: "Kind", priority: "secondary" as const },
  { key: "format", header: "Format", priority: "tertiary" as const },
  { key: "status", header: "Status", priority: "secondary" as const },
  { key: "ops", header: <span className="visually-hidden">Operations</span>, className: "text-end" },
];

export function ResumeListSection({
  enabled,
  templateResumeId,
  onSectionDirty,
}: {
  readonly enabled: boolean;
  readonly templateResumeId: string;
  readonly onSectionDirty?: (dirty: boolean) => void;
}) {
  const resume = useResume();
  const items = resume.resumes.data?.items ?? NO_RESUMES;
  const [params, setParams] = useSearchParams();
  const openId = params.get("resume");
  const [filter, setFilter] = useState("");
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [pendingId, setPendingId] = useState<string | null | undefined>(undefined);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    onSectionDirty?.(dirty);
    return () => onSectionDirty?.(false);
  }, [dirty, onSectionDirty]);

  const visible = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return items;
    return items.filter((row) => row.title.toLowerCase().includes(query));
  }, [filter, items]);

  useEffect(() => {
    if (!openId || openId === DRAFT_RECORD_ID || resume.resumes.isLoading) return;
    if (!items.some((row) => row.id === openId)) {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          next.delete("resume");
          return next;
        },
        { replace: true },
      );
    }
  }, [items, openId, resume.resumes.isLoading, setParams]);

  function setOpen(id: string | null) {
    setDirty(false);
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (id) next.set("resume", id);
        else next.delete("resume");
        return next;
      },
      { replace: true },
    );
  }

  function requestOpen(id: string | null) {
    if (dirty && id !== openId) {
      setPendingId(id);
      return;
    }
    setOpen(id);
  }

  return (
    <>
      {actionError ? (
        <div className="alert alert-danger py-2 small" role="alert">
          {actionError}
        </div>
      ) : null}
      {resume.deleteResume.isError ? (
        <div className="alert alert-danger py-2 small" role="alert">
          {getAdminApiErrorMessage(resume.deleteResume.error) ?? "Could not delete the resume."}
        </div>
      ) : null}
      {resume.setTemplate.isError ? (
        <div className="alert alert-danger py-2 small" role="alert">
          {getAdminApiErrorMessage(resume.setTemplate.error) ?? "Could not make this the template."}
        </div>
      ) : null}
      <AdminRecordTable
        label="Resumes"
        filters={
          <AdminFilterBar
            create={
              <AdminCreateButton
                label="Add resume"
                disabled={!enabled}
                onClick={() => requestOpen(DRAFT_RECORD_ID)}
              />
            }
          >
            <AdminFilterField label="Filter" htmlFor="resume-filter">
              <input
                id="resume-filter"
                className="form-control form-control-sm"
                value={filter}
                placeholder="Title"
                onChange={(event) => setFilter(event.target.value)}
              />
            </AdminFilterField>
          </AdminFilterBar>
        }
      >
        <AdminDataTable columns={COLUMNS} bare>
          {visible.length === 0 && openId !== DRAFT_RECORD_ID ? (
            <AdminDataTableEmptyRow colSpan={COLUMNS.length} message="No resumes yet." />
          ) : (
            visible.map((row) => (
              <ResumeRow
                key={row.id}
                row={row}
                enabled={enabled}
                expanded={openId === row.id}
                isTemplate={row.id === templateResumeId || row.kind === "template"}
                onToggle={() => requestOpen(openId === row.id ? null : row.id)}
                onDirty={setDirty}
                onDelete={() => setDeleteId(row.id)}
                onActionError={setActionError}
              />
            ))
          )}
          {openId === DRAFT_RECORD_ID ? (
            <ResumeDraftRow enabled={enabled} onClose={() => setOpen(null)} onDirty={setDirty} />
          ) : null}
        </AdminDataTable>
      </AdminRecordTable>
      <ConfirmDialog
        open={deleteId !== null}
        title="Delete this resume?"
        body="The Word file and its rendered PDF are removed. The template and a resume used by the tracker stay."
        confirmLabel="Delete"
        tone="danger"
        onCancel={() => setDeleteId(null)}
        onConfirm={() => {
          const id = deleteId;
          if (!id) return;
          void resume.deleteResume.mutateAsync(id).then(
            () => {
              if (id === openId) setOpen(null);
            },
            () => undefined,
          );
          setDeleteId(null);
        }}
      />
      <ConfirmDialog
        open={pendingId !== undefined}
        title="Discard unsaved edits?"
        body="This resume has unsaved changes."
        confirmLabel="Discard"
        cancelLabel="Keep editing"
        tone="danger"
        onCancel={() => setPendingId(undefined)}
        onConfirm={() => {
          setOpen(pendingId ?? null);
          setPendingId(undefined);
        }}
      />
    </>
  );
}

function ResumeRow({
  row,
  enabled,
  expanded,
  isTemplate,
  onToggle,
  onDirty,
  onDelete,
  onActionError,
}: {
  readonly row: ResumeSummary;
  readonly enabled: boolean;
  readonly expanded: boolean;
  readonly isTemplate: boolean;
  readonly onToggle: () => void;
  readonly onDirty: (dirty: boolean) => void;
  readonly onDelete: () => void;
  readonly onActionError: (message: string | null) => void;
}) {
  const resume = useResume();
  const detail = useResumeDetail(expanded ? row.id : null);
  const [overrides, setOverrides] = useState<Record<string, "locked" | "rewritable"> | null>(null);
  const ready = row.extract.status === "ready";
  const item = detail.data?.item;
  const saved = item?.layout.overrides ?? {};
  const effective = overrides ?? saved;
  const dirty = JSON.stringify(effective) !== JSON.stringify(saved);

  useEffect(() => {
    onDirty(expanded && dirty);
  }, [dirty, expanded, onDirty]);

  async function download(kind: "file" | "pdf", open: boolean) {
    const preview = open ? openPreview() : null;
    try {
      const body = await fetchResumeFile(row.id, kind);
      onActionError(null);
      if (open) showPreview(preview, body.filename, body.contentType, body.dataBase64);
      else downloadBase64(body.filename, body.contentType, body.dataBase64);
    } catch (caught) {
      preview?.close();
      onActionError(getAdminApiErrorMessage(caught) ?? "Could not download the resume.");
    }
  }

  return (
    <AdminExpandableRow
      colSpan={COLUMNS.length}
      expanded={expanded}
      onToggle={onToggle}
      editor={
        item ? (
          <AdminEditorPanel
            formId={`resume-${row.id}`}
            submitLabel="Save"
            isSaving={resume.patchResume.isPending}
            savingLabel="Saving…"
            disabled={!enabled || row.kind === "tailored" || !dirty}
            hideSubmit={row.kind === "tailored"}
            error={
              resume.patchResume.isError
                ? getAdminApiErrorMessage(resume.patchResume.error) ?? "Could not save the resume."
                : null
            }
            onSubmit={(event) => {
              event.preventDefault();
              void resume.patchResume.mutateAsync({ id: row.id, overrides: effective }).then(() => {
                setOverrides(null);
                onDirty(false);
              });
            }}
          >
            {row.kind === "tailored" ? (
              <p className="small text-muted">This tailored resume is kept as generated. Run New resume again to change it.</p>
            ) : null}
            <p className="small text-muted">
              PDF is a rendered copy. Download the original file when you need the upload itself.
            </p>
            {(item.generation?.findings ?? []).map((finding) => (
              <p key={finding} className="small mb-1">
                {finding}
              </p>
            ))}
            <ResumeTemplateMap
              detail={item}
              overrides={effective}
              readOnly={!enabled || row.kind === "tailored"}
              onOverride={(id, value) => {
                setOverrides((current) => {
                  const next = { ...(current ?? saved) };
                  if (!value) delete next[id];
                  else next[id] = value;
                  return next;
                });
              }}
            />
          </AdminEditorPanel>
        ) : (
          <p className="small text-muted mb-0">{detail.isError ? "Could not load this resume." : "Loading…"}</p>
        )
      }
    >
      <AdminCell column="title">
        {row.title}{" "}
        {isTemplate ? <span className="badge text-bg-secondary">Template</span> : null}
      </AdminCell>
      <AdminCell column="kind">{kindLabel(row.kind)}</AdminCell>
      <AdminCell column="format">{row.format}</AdminCell>
      <AdminCell column="status">{row.extract.status === "failed" ? row.extract.error || "Failed" : row.extract.status}</AdminCell>
      <AdminCell column="ops" className="text-end">
        <AdminRowActions
          actions={[
            {
              id: "view",
              label: ready ? "View" : "View (not ready yet)",
              iconClassName: "bi-eye",
              disabled: !ready,
              onClick: () => void download("pdf", true),
            },
            {
              id: "docx",
              label: row.format === "docx" ? "Download .docx" : "Download .docx (Word only)",
              iconClassName: "bi-file-earmark-word",
              hidden: row.format !== "docx",
              onClick: () => void download("file", false),
            },
            {
              id: "original",
              label: row.format === "pdf" ? "Download original PDF" : "Download original",
              iconClassName: "bi-download",
              hidden: row.format === "docx",
              onClick: () => void download("file", false),
            },
            {
              id: "pdf",
              label: ready ? "Download PDF" : "Download PDF (not ready yet)",
              iconClassName: "bi-file-earmark-pdf",
              disabled: !ready,
              onClick: () => void download("pdf", false),
            },
            {
              id: "template",
              label: row.format === "docx" && ready ? "Make template" : "Make template (ready Word only)",
              iconClassName: "bi-bookmark",
              hidden: !enabled || isTemplate,
              disabled: row.format !== "docx" || !ready,
              onClick: () => void resume.setTemplate.mutate(row.id),
            },
            {
              id: "delete",
              label: "Delete",
              iconClassName: "bi-trash",
              danger: true,
              hidden: !enabled,
              onClick: onDelete,
            },
          ]}
        />
      </AdminCell>
    </AdminExpandableRow>
  );
}

function ResumeDraftRow({
  enabled,
  onClose,
  onDirty,
}: {
  readonly enabled: boolean;
  readonly onClose: () => void;
  readonly onDirty: (dirty: boolean) => void;
}) {
  const resume = useResume();
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [makeTemplate, setMakeTemplate] = useState(true);
  const [localError, setLocalError] = useState<string | null>(null);
  const formId = "resume-new";

  useEffect(() => {
    onDirty(Boolean(file) || title.trim() !== "");
  }, [file, onDirty, title]);

  return (
    <AdminExpandableRow
      colSpan={COLUMNS.length}
      expanded
      onToggle={onClose}
      editor={
        <AdminEditorPanel
          formId={formId}
          submitLabel="Upload"
          savingLabel="Uploading…"
          isSaving={resume.upload.isPending}
          disabled={!enabled}
          error={localError}
          onSubmit={(event) => {
            event.preventDefault();
            if (!file) {
              setLocalError("Choose a file.");
              return;
            }
            const contentType = contentTypeForFile(file.name, file.type);
            if (!contentType) {
              setLocalError("Upload a .docx Word document. Legacy .doc files are not accepted.");
              return;
            }
            if (makeTemplate && !file.name.toLowerCase().endsWith(".docx")) {
              setLocalError("Only a Word document can be the template.");
              return;
            }
            setLocalError(null);
            void readFileBase64(file)
              .then((dataBase64) => resume.upload.mutateAsync({ title, contentType, dataBase64, makeTemplate }))
              .then(onClose)
              .catch((error: unknown) => {
                setLocalError(getAdminApiErrorMessage(error) ?? "Could not upload the resume.");
              });
          }}
        >
          <AdminFieldGrid columns={1}>
            <AdminField label="Title" htmlFor={`${formId}-title`}>
              <input
                id={`${formId}-title`}
                className="form-control"
                value={title}
                required
                onChange={(event) => setTitle(event.target.value)}
              />
            </AdminField>
            <AdminField label="File" htmlFor={`${formId}-file`}>
              <input
                id={`${formId}-file`}
                className="form-control"
                type="file"
                accept=".docx,.pdf,.md,.txt,application/pdf,text/plain,text/markdown"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </AdminField>
            <AdminField label="Template" htmlFor={`${formId}-template`}>
              <div className="form-check">
                <input
                  id={`${formId}-template`}
                  className="form-check-input"
                  type="checkbox"
                  checked={makeTemplate}
                  onChange={(event) => setMakeTemplate(event.target.checked)}
                />
                <label className="form-check-label" htmlFor={`${formId}-template`}>
                  Make this the template after it is read
                </label>
              </div>
            </AdminField>
          </AdminFieldGrid>
        </AdminEditorPanel>
      }
    >
      <AdminCell column="title">New resume</AdminCell>
      <AdminCell column="kind">—</AdminCell>
      <AdminCell column="format">—</AdminCell>
      <AdminCell column="status">New</AdminCell>
      <AdminCell column="ops" />
    </AdminExpandableRow>
  );
}
