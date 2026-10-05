import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useLinkedIn } from "../../hooks/useLinkedIn";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import { DRAFT_RECORD_ID } from "../../lib/expandedRecord";
import { pillarLabel, type LinkedInDraftSettings } from "../../lib/linkedinModel";
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

const COLUMNS = [
  { key: "text", header: "Idea" },
  { key: "pillar", header: "Pillar", priority: "secondary" as const },
  { key: "status", header: "Status", priority: "secondary" as const },
  { key: "ops", header: <span className="visually-hidden">Operations</span>, className: "text-end" },
];

export function LinkedInIdeasSection({
  settings,
  enabled,
}: {
  readonly settings: LinkedInDraftSettings | undefined;
  readonly enabled: boolean;
}) {
  const linkedIn = useLinkedIn();
  const ideas = linkedIn.ideas.data?.items ?? [];
  const [params, setParams] = useSearchParams();
  const openId = params.get("linkedin-idea");
  const [deleteId, setDeleteId] = useState<string | null>(null);

  function setOpen(id: string | null) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (id) next.set("linkedin-idea", id);
      else next.delete("linkedin-idea");
      return next;
    }, { replace: true });
  }

  return (
    <>
      <AdminRecordTable
        label="LinkedIn ideas"
        filters={
          <AdminFilterBar
            create={<AdminCreateButton label="New idea" disabled={!enabled} onClick={() => setOpen(DRAFT_RECORD_ID)} />}
          />
        }
      >
        <AdminDataTable columns={COLUMNS} bare>
          {ideas.length === 0 && openId !== DRAFT_RECORD_ID ? (
            <AdminDataTableEmptyRow colSpan={COLUMNS.length} message="No ideas yet." />
          ) : (
            ideas.map((idea) => (
              <tr key={idea.ideaId}>
                <AdminCell column="text">{idea.text}</AdminCell>
                <AdminCell column="pillar">{idea.pillar ? pillarLabel(idea.pillar) : "—"}</AdminCell>
                <AdminCell column="status">{idea.status === "used" ? "Used" : "New"}</AdminCell>
                <AdminCell column="ops" className="text-end">
                  <AdminRowActions
                    actions={[
                      {
                        id: "delete",
                        label: "Delete",
                        iconClassName: "bi-trash",
                        danger: true,
                        hidden: !enabled,
                        onClick: () => setDeleteId(idea.ideaId),
                      },
                    ]}
                  />
                </AdminCell>
              </tr>
            ))
          )}
          {openId === DRAFT_RECORD_ID && settings ? (
            <IdeaDraftRow settings={settings} enabled={enabled} onClose={() => setOpen(null)} />
          ) : null}
        </AdminDataTable>
      </AdminRecordTable>
      <ConfirmDialog
        open={deleteId !== null}
        title="Delete this idea?"
        body="A draft already written from it stays in the queue."
        confirmLabel="Delete"
        tone="danger"
        onCancel={() => setDeleteId(null)}
        onConfirm={() => {
          if (deleteId) void linkedIn.deleteIdea.mutate(deleteId);
          setDeleteId(null);
        }}
      />
    </>
  );
}

function IdeaDraftRow({
  settings,
  enabled,
  onClose,
}: {
  readonly settings: LinkedInDraftSettings;
  readonly enabled: boolean;
  readonly onClose: () => void;
}) {
  const linkedIn = useLinkedIn();
  const [text, setText] = useState("");
  const [pillar, setPillar] = useState("");
  const formId = "linkedin-idea-new";
  return (
    <AdminExpandableRow colSpan={COLUMNS.length} expanded onToggle={onClose} editor={
      <AdminEditorPanel
        formId={formId}
        submitLabel="Add idea"
        isSaving={linkedIn.createIdea.isPending}
        disabled={!enabled}
        error={
          linkedIn.createIdea.error
            ? getAdminApiErrorMessage(linkedIn.createIdea.error) ?? "Could not add the idea."
            : null
        }
        onSubmit={(event) => {
          event.preventDefault();
          if (!enabled) return;
          void linkedIn.createIdea.mutateAsync({ text, pillar }).then(onClose);
        }}
      >
        <AdminFieldGrid columns={1}>
          <AdminField label="Idea" htmlFor={`${formId}-text`}>
            <textarea
              id={`${formId}-text`}
              className="form-control"
              rows={3}
              value={text}
              maxLength={500}
              onChange={(event) => setText(event.target.value)}
            />
          </AdminField>
          <AdminField label="Pillar" htmlFor={`${formId}-pillar`}>
            <select
              id={`${formId}-pillar`}
              className="form-select"
              value={pillar}
              onChange={(event) => setPillar(event.target.value)}
            >
              <option value="">Any pillar</option>
              {settings.pillars.map((id) => (
                <option key={id} value={id}>{pillarLabel(id)}</option>
              ))}
            </select>
          </AdminField>
        </AdminFieldGrid>
      </AdminEditorPanel>
    }>
      <AdminCell column="text">New idea</AdminCell>
      <AdminCell column="pillar">—</AdminCell>
      <AdminCell column="status">New</AdminCell>
      <AdminCell column="ops" />
    </AdminExpandableRow>
  );
}

(IdeaDraftRow as { recordGroup?: boolean }).recordGroup = true;
