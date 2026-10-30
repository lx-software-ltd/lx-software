import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useResume } from "../../hooks/useResume";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import { DRAFT_RECORD_ID } from "../../lib/expandedRecord";
import {
  APPLICATION_STATUSES,
  statusLabel,
  type JobApplication,
  type JobPosting,
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
  AdminRecordTable,
  AdminRowActions,
  ConfirmDialog,
} from "../ui";

const NO_APPLICATIONS: JobApplication[] = [];
const NO_RESUMES: ResumeSummary[] = [];
const NO_POSTINGS: JobPosting[] = [];

const COLUMNS = [
  { key: "company", header: "Company" },
  { key: "position", header: "Position", priority: "secondary" as const },
  { key: "status", header: "Status", priority: "secondary" as const },
  { key: "resume", header: "Resume", priority: "tertiary" as const },
  { key: "ops", header: <span className="visually-hidden">Operations</span>, className: "text-end" },
];

const EMPTY = {
  company: "",
  position: "",
  status: "saved",
  resumeId: "",
  postingId: "",
  appliedAt: "",
  nextStepAt: "",
  notes: "",
  name: "",
  email: "",
  phone: "",
};

export function ResumeTrackerSection({
  enabled,
  onSectionDirty,
}: {
  readonly enabled: boolean;
  readonly onSectionDirty?: (dirty: boolean) => void;
}) {
  const resume = useResume();
  const items = resume.applications.data?.items ?? NO_APPLICATIONS;
  const resumes = resume.resumes.data?.items ?? NO_RESUMES;
  const postings = resume.postings.data?.items ?? NO_POSTINGS;
  const [params, setParams] = useSearchParams();
  const openId = params.get("application");
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [pendingId, setPendingId] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    onSectionDirty?.(dirty);
    return () => onSectionDirty?.(false);
  }, [dirty, onSectionDirty]);

  useEffect(() => {
    if (!openId || openId === DRAFT_RECORD_ID || resume.applications.isLoading) return;
    if (!items.some((row) => row.id === openId)) {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          next.delete("application");
          return next;
        },
        { replace: true },
      );
    }
  }, [items, openId, resume.applications.isLoading, setParams]);

  function setOpen(id: string | null) {
    setDirty(false);
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (id) next.set("application", id);
        else next.delete("application");
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

  const names = useMemo(() => new Map(resumes.map((row) => [row.id, row.title])), [resumes]);

  return (
    <>
      {resume.deleteApplication.isError ? (
        <div className="alert alert-danger py-2 small" role="alert">
          {getAdminApiErrorMessage(resume.deleteApplication.error) ?? "Could not delete the application."}
        </div>
      ) : null}
      <AdminRecordTable
        label="Job tracker"
        filters={
          <AdminFilterBar
            create={
              <AdminCreateButton label="Add application" disabled={!enabled} onClick={() => requestOpen(DRAFT_RECORD_ID)} />
            }
          />
        }
      >
        <AdminDataTable columns={COLUMNS} bare>
          {items.length === 0 && openId !== DRAFT_RECORD_ID ? (
            <AdminDataTableEmptyRow colSpan={COLUMNS.length} message="No applications yet." />
          ) : (
            items.map((row) => (
              <ApplicationRow
                key={`${row.id}:${row.updatedAt}`}
                row={row}
                enabled={enabled}
                expanded={openId === row.id}
                resumeTitle={names.get(row.resumeId) || "—"}
                resumes={resumes.map((item) => ({ id: item.id, title: item.title }))}
                postings={postings.map((item) => ({ id: item.id, title: item.title, company: item.company }))}
                onToggle={() => requestOpen(openId === row.id ? null : row.id)}
                onDirty={setDirty}
                onDelete={() => setDeleteId(row.id)}
              />
            ))
          )}
          {openId === DRAFT_RECORD_ID ? (
            <ApplicationRow
              row={null}
              enabled={enabled}
              expanded
              resumeTitle="—"
              resumes={resumes.map((item) => ({ id: item.id, title: item.title }))}
              postings={postings.map((item) => ({ id: item.id, title: item.title, company: item.company }))}
              onToggle={() => requestOpen(null)}
              onSaved={() => setOpen(null)}
              onDirty={setDirty}
              onDelete={() => undefined}
            />
          ) : null}
        </AdminDataTable>
      </AdminRecordTable>
      <ConfirmDialog
        open={deleteId !== null}
        title="Delete this application?"
        body="The resume and the job post stay."
        confirmLabel="Delete"
        tone="danger"
        onCancel={() => setDeleteId(null)}
        onConfirm={() => {
          const id = deleteId;
          if (!id) return;
          void resume.deleteApplication.mutateAsync(id).then(
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
        body="This application has unsaved changes."
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

function ApplicationRow({
  row,
  enabled,
  expanded,
  resumeTitle,
  resumes,
  postings,
  onToggle,
  onDirty,
  onDelete,
  onSaved,
}: {
  readonly row: JobApplication | null;
  readonly enabled: boolean;
  readonly expanded: boolean;
  readonly resumeTitle: string;
  readonly resumes: readonly { id: string; title: string }[];
  readonly postings: readonly { id: string; title: string; company: string }[];
  readonly onToggle: () => void;
  readonly onDirty: (dirty: boolean) => void;
  readonly onDelete: () => void;
  readonly onSaved?: () => void;
}) {
  const resume = useResume();
  const saved = row
    ? {
        company: row.company,
        position: row.position,
        status: row.status,
        resumeId: row.resumeId,
        postingId: row.postingId,
        appliedAt: row.appliedAt,
        nextStepAt: row.nextStepAt,
        notes: row.notes,
        name: row.recruiter.name,
        email: row.recruiter.email,
        phone: row.recruiter.phone,
      }
    : EMPTY;
  const [form, setForm] = useState(saved);
  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  useEffect(() => {
    onDirty(expanded && dirty);
  }, [dirty, expanded, onDirty]);
  const formId = `application-${row?.id ?? "new"}`;

  return (
    <AdminExpandableRow
      colSpan={COLUMNS.length}
      expanded={expanded}
      onToggle={onToggle}
      editor={
        <AdminEditorPanel
          formId={formId}
          submitLabel={row ? "Save" : "Add"}
          savingLabel="Saving…"
          isSaving={resume.saveApplication.isPending}
          disabled={!enabled || !dirty}
          error={
            resume.saveApplication.isError
              ? getAdminApiErrorMessage(resume.saveApplication.error) ?? "Could not save the application."
              : null
          }
          onSubmit={(event) => {
            event.preventDefault();
            void resume.saveApplication
              .mutateAsync({
                id: row?.id,
                company: form.company,
                position: form.position,
                status: form.status,
                resumeId: form.resumeId,
                postingId: form.postingId,
                appliedAt: form.appliedAt,
                nextStepAt: form.nextStepAt,
                notes: form.notes,
                recruiter: { name: form.name, email: form.email, phone: form.phone },
              })
              .then(() => {
                onDirty(false);
                if (!row) onSaved?.();
              });
          }}
        >
          <AdminFieldGrid columns={2}>
            <AdminField label="Company" htmlFor={`${formId}-company`}>
              <input id={`${formId}-company`} className="form-control" value={form.company} onChange={(event) => setForm({ ...form, company: event.target.value })} />
            </AdminField>
            <AdminField label="Position" htmlFor={`${formId}-position`}>
              <input id={`${formId}-position`} className="form-control" value={form.position} onChange={(event) => setForm({ ...form, position: event.target.value })} />
            </AdminField>
            <AdminField label="Status" htmlFor={`${formId}-status`}>
              <select id={`${formId}-status`} className="form-select" value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>
                {APPLICATION_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {statusLabel(status)}
                  </option>
                ))}
              </select>
            </AdminField>
            <AdminField label="Resume" htmlFor={`${formId}-resume`}>
              <select id={`${formId}-resume`} className="form-select" value={form.resumeId} onChange={(event) => setForm({ ...form, resumeId: event.target.value })}>
                <option value="">None</option>
                {resumes.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </AdminField>
            <AdminField label="Job post" htmlFor={`${formId}-posting`}>
              <select
                id={`${formId}-posting`}
                className="form-select"
                value={form.postingId}
                onChange={(event) => setForm({ ...form, postingId: event.target.value })}
              >
                <option value="">None</option>
                {postings.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.company} — {item.title}
                  </option>
                ))}
              </select>
            </AdminField>
            <AdminField label="Applied" htmlFor={`${formId}-applied`}>
              <input id={`${formId}-applied`} className="form-control" type="date" value={form.appliedAt} onChange={(event) => setForm({ ...form, appliedAt: event.target.value })} />
            </AdminField>
            <AdminField label="Next step" htmlFor={`${formId}-next`}>
              <input id={`${formId}-next`} className="form-control" type="date" value={form.nextStepAt} onChange={(event) => setForm({ ...form, nextStepAt: event.target.value })} />
            </AdminField>
            <AdminField label="Recruiter name" htmlFor={`${formId}-name`}>
              <input id={`${formId}-name`} className="form-control" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
            </AdminField>
            <AdminField label="Recruiter email" htmlFor={`${formId}-email`}>
              <input id={`${formId}-email`} className="form-control" type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />
            </AdminField>
            <AdminField label="Recruiter phone" htmlFor={`${formId}-phone`}>
              <input id={`${formId}-phone`} className="form-control" value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} />
            </AdminField>
            <AdminField label="Notes" htmlFor={`${formId}-notes`} span={2}>
              <textarea id={`${formId}-notes`} className="form-control" rows={3} value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
            </AdminField>
          </AdminFieldGrid>
        </AdminEditorPanel>
      }
    >
      <AdminCell column="company">{row?.company ?? "New application"}</AdminCell>
      <AdminCell column="position">{row?.position ?? "—"}</AdminCell>
      <AdminCell column="status">{row ? statusLabel(row.status) : "New"}</AdminCell>
      <AdminCell column="resume">{resumeTitle}</AdminCell>
      <AdminCell column="ops" className="text-end">
        {row ? (
          <AdminRowActions
            actions={[
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
        ) : null}
      </AdminCell>
    </AdminExpandableRow>
  );
}
