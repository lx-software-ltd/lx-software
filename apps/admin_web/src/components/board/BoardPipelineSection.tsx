import { useMemo, useRef, useState } from "react";
import {
  AdminCell,
  AdminDataTable,
  AdminDataTableEmptyRow,
  AdminDisclosure,
  AdminEditorSection,
  AdminExpandableRow,
  AdminFilterBar,
  AdminFilterField,
  AdminRecordTable,
  ConfirmDialog,
} from "../ui";
import { useExpandedRecord } from "../../hooks/useExpandedRecord";
import { useBoardPipeline, useBoardSequence } from "../../hooks/useBoardPipeline";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import type { BoardProspect, BoardProspectWrite, BoardSequenceStep } from "../../lib/boardModel";
import { BOARD_STAFF_PROSPECT_STAGES, BOARD_STAFF_PROSPECT_TYPES } from "../../lib/contracts/generated";

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

const COLUMNS = [
  { key: "name", header: "Name" },
  { key: "type", header: "Type", priority: "secondary" as const },
  { key: "district", header: "District", priority: "secondary" as const },
  { key: "stage", header: "Stage" },
  { key: "score", header: "Score", priority: "secondary" as const },
] as const;

const OWNER_STAGES = ["suppressed", "declined", "qualified", "parked"] as const;

function emptyStep(): BoardSequenceStep {
  return { dayOffset: 0, subjectEn: "", subjectZh: "", bodyEn: "", bodyZh: "" };
}

export function BoardPipelineSection() {
  const pipeline = useBoardPipeline();
  const [stage, setStage] = useState("");
  const [ptype, setPtype] = useState("");
  const [district, setDistrict] = useState("");
  const [scoreMin, setScoreMin] = useState("");
  const [filter, setFilter] = useState("");
  const expanded = useExpandedRecord("prospect");
  const selectedId = expanded.expandedId;
  const prospectDirtyRef = useRef(false);
  const [csv, setCsv] = useState("name,type,district,website,email\n");
  const [seqType, setSeqType] = useState("provider");
  const sequence = useBoardSequence(seqType);
  const [seqDraft, setSeqDraft] = useState<BoardSequenceStep[] | null>(null);

  const selected =
    pipeline.prospects.find((p) => p.prospectId === selectedId) ??
    pipeline.needsContact.find((p) => p.prospectId === selectedId) ??
    null;
  const selectedInLoadedPage = pipeline.prospects.some((p) => p.prospectId === selectedId);
  const steps = seqDraft ?? sequence.data?.steps ?? [];

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const min = scoreMin === "" ? null : Number(scoreMin);
    return pipeline.prospects.filter((p) => {
      if (stage && p.stage !== stage) return false;
      if (ptype && p.type !== ptype) return false;
      if (district && (p.district || "").toLowerCase() !== district.toLowerCase()) return false;
      if (min !== null && !Number.isNaN(min) && (p.score ?? 0) < min) return false;
      if (!q) return true;
      return [p.name, p.district, p.website, p.stage].join(" ").toLowerCase().includes(q);
    });
  }, [pipeline.prospects, stage, ptype, district, scoreMin, filter]);

  const funnel = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const s of BOARD_STAFF_PROSPECT_STAGES) counts[s] = 0;
    for (const p of pipeline.prospects) counts[p.stage || "discovered"] = (counts[p.stage || "discovered"] ?? 0) + 1;
    return counts;
  }, [pipeline.prospects]);

  const stats = pipeline.stats;
  const target = 50;

  return (
    <div className="d-flex flex-column gap-3">
      <section>
        <h2 className="h5 mb-2">Pipeline</h2>
        <p className="small text-muted mb-2">
          Qualified this week vs weekly target {target}. Stages:
          {BOARD_STAFF_PROSPECT_STAGES.map((s) => ` ${s} ${funnel[s] ?? 0}`).join(" ·")}
        </p>
        <div className="progress mb-2" role="img" aria-label="Qualified vs target">
          <div
            className="progress-bar"
            style={{ width: `${Math.min(100, Math.round(((funnel.qualified + funnel.contacted + funnel.replied) / target) * 100))}%` }}
          />
        </div>
      </section>

      <AdminRecordTable
        label="Prospects"
        filters={
          <AdminFilterBar>
            <AdminFilterField label="Filter" htmlFor="pipe-filter">
              <input
                id="pipe-filter"
                type="search"
                className="form-control form-control-sm"
                placeholder="Filter prospects"
                autoComplete="off"
                value={filter}
                onChange={(ev) => setFilter(ev.target.value)}
              />
            </AdminFilterField>
            <AdminFilterField label="Stage" htmlFor="pipe-stage">
              <select id="pipe-stage" className="form-select form-select-sm" value={stage} onChange={(e) => setStage(e.target.value)}>
                <option value="">All</option>
                {BOARD_STAFF_PROSPECT_STAGES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </AdminFilterField>
            <AdminFilterField label="Type" htmlFor="pipe-type">
              <select id="pipe-type" className="form-select form-select-sm" value={ptype} onChange={(e) => setPtype(e.target.value)}>
                <option value="">All</option>
                {BOARD_STAFF_PROSPECT_TYPES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </AdminFilterField>
            <AdminFilterField label="District" htmlFor="pipe-district">
              <input id="pipe-district" className="form-control form-control-sm" value={district} onChange={(e) => setDistrict(e.target.value)} />
            </AdminFilterField>
            <AdminFilterField label="Min score" htmlFor="pipe-score">
              <input id="pipe-score" className="form-control form-control-sm" value={scoreMin} onChange={(e) => setScoreMin(e.target.value)} />
            </AdminFilterField>
          </AdminFilterBar>
        }
        beforeTable={
          <AdminDisclosure title="CSV import">
            <label className="form-label small" htmlFor="pipe-csv">name,type,district,website,email (≤ 500 rows)</label>
            <textarea id="pipe-csv" className="form-control font-monospace small" rows={4} value={csv} onChange={(e) => setCsv(e.target.value)} />
            <button
              type="button"
              className="btn btn-sm btn-outline-primary mt-2"
              disabled={pipeline.importCsv.isPending}
              onClick={() => pipeline.importCsv.mutate(csv)}
            >
              {pipeline.importCsv.isPending ? "Uploading…" : "Import"}
            </button>
            {pipeline.importCsv.data ? (
              <p className="small mt-2 mb-0">
                Created {pipeline.importCsv.data.created}, updated {pipeline.importCsv.data.updated}
                {pipeline.importCsv.data.errors.length ? `; ${pipeline.importCsv.data.errors.join("; ")}` : ""}
              </p>
            ) : null}
            {errorText(pipeline.importCsv.error) ? <p className="small text-danger mt-2 mb-0">{errorText(pipeline.importCsv.error)}</p> : null}
          </AdminDisclosure>
        }
      >
      <AdminDataTable bare columns={COLUMNS}>
        {filtered.length === 0 ? (
          <AdminDataTableEmptyRow colSpan={COLUMNS.length} message="No prospects yet." />
        ) : (
          filtered.map((p) => (
            <AdminExpandableRow
              key={p.prospectId}
              colSpan={COLUMNS.length}
              expanded={selectedId === p.prospectId}
              onToggle={() =>
                expanded.toggle(
                  p.prospectId,
                  prospectDirtyRef.current,
                  () => {
                    prospectDirtyRef.current = false;
                  },
                  () => {
                    prospectDirtyRef.current = false;
                  },
                )
              }
              editor={
                selected && selected.prospectId === p.prospectId ? (
                  <ProspectEditor
                    key={selected.prospectId}
                    prospect={selected}
                    error={errorText(pipeline.update.error) ?? errorText(pipeline.merge.error)}
                    saving={pipeline.update.isPending}
                    onDirty={(dirty) => {
                      prospectDirtyRef.current = dirty;
                    }}
                    onSave={(body) => pipeline.update.mutate({ prospectId: selected.prospectId, body })}
                    onMerge={(into) => pipeline.merge.mutate({ prospectId: selected.prospectId, into })}
                  />
                ) : null
              }
            >
              <AdminCell column="name">{p.name}</AdminCell>
              <AdminCell column="type">{p.type}</AdminCell>
              <AdminCell column="district">{p.district}</AdminCell>
              <AdminCell column="stage">{p.stage}</AdminCell>
              <AdminCell column="score">{p.score ?? "—"}</AdminCell>
            </AdminExpandableRow>
          ))
        )}
      </AdminDataTable>
      {pipeline.hasNextPage ? (
        <div className="px-3 pb-3">
          <button
            type="button"
            className="btn btn-outline-secondary btn-sm"
            onClick={() => void pipeline.fetchNextPage()}
          >
            Load more
          </button>
        </div>
      ) : null}
      <ConfirmDialog
        open={expanded.confirmOpen}
        title="Discard unsaved edits?"
        body="This prospect has unsaved changes."
        confirmLabel="Discard"
        cancelLabel="Keep editing"
        tone="danger"
        onConfirm={expanded.acceptPending}
        onCancel={expanded.cancelPending}
      />
      </AdminRecordTable>

      <AdminEditorSection title="Needs a contact">
        {selected && !selectedInLoadedPage ? (
          <div className="mb-3">
            <ProspectEditor
              key={selected.prospectId}
              prospect={selected}
              error={errorText(pipeline.update.error) ?? errorText(pipeline.merge.error)}
              saving={pipeline.update.isPending || pipeline.merge.isPending}
              onDirty={(dirty) => {
                prospectDirtyRef.current = dirty;
              }}
              onSave={(body) => pipeline.update.mutate({ prospectId: selected.prospectId, body })}
              onMerge={(into) => pipeline.merge.mutate({ prospectId: selected.prospectId, into })}
            />
          </div>
        ) : null}
        {pipeline.needsContact.length === 0 ? (
          <p className="small text-muted mb-0">No qualified prospects are waiting for a business address.</p>
        ) : (
          <ul className="small mb-0">
            {pipeline.needsContact.map((p) => (
              <li key={p.prospectId}>
                <button
                  type="button"
                  className="btn btn-link btn-sm p-0"
                  onClick={() => {
                    setStage("");
                    setPtype("");
                    setDistrict("");
                    setScoreMin("");
                    setFilter("");
                    expanded.request(p.prospectId, prospectDirtyRef.current);
                  }}
                >
                  {p.name}
                </button>
                {" "}({p.district || "unknown"})
              </li>
            ))}
          </ul>
        )}
      </AdminEditorSection>

      <AdminEditorSection title="Sequences">
        <label className="form-label small" htmlFor="pipe-seq-type">Type</label>
        <select
          id="pipe-seq-type"
          className="form-select form-select-sm w-auto"
          value={seqType}
          onChange={(e) => {
            setSeqType(e.target.value);
            setSeqDraft(null);
          }}
        >
          {BOARD_STAFF_PROSPECT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        {steps.map((step, i) => (
          <div key={`${seqType}-${i}`} className="border rounded p-2 mt-2">
            <div className="small fw-semibold mb-1">Step {i + 1} (day {step.dayOffset})</div>
            <label className="form-label small mb-1" htmlFor={`seq-en-${i}`}>Subject EN</label>
            <input
              id={`seq-en-${i}`}
              className="form-control form-control-sm mb-1"
              value={step.subjectEn}
              onChange={(e) => {
                const next = steps.map((s, idx) => (idx === i ? { ...s, subjectEn: e.target.value } : s));
                setSeqDraft(next);
              }}
            />
            <label className="form-label small mb-1" htmlFor={`seq-zh-${i}`}>Subject ZH</label>
            <input
              id={`seq-zh-${i}`}
              className="form-control form-control-sm mb-1"
              value={step.subjectZh}
              onChange={(e) => {
                const next = steps.map((s, idx) => (idx === i ? { ...s, subjectZh: e.target.value } : s));
                setSeqDraft(next);
              }}
            />
            <label className="form-label small mb-1" htmlFor={`seq-body-en-${i}`}>Body EN</label>
            <textarea
              id={`seq-body-en-${i}`}
              className="form-control form-control-sm mb-1"
              rows={3}
              value={step.bodyEn}
              onChange={(e) => {
                const next = steps.map((s, idx) => (idx === i ? { ...s, bodyEn: e.target.value } : s));
                setSeqDraft(next);
              }}
            />
            <label className="form-label small mb-1" htmlFor={`seq-body-zh-${i}`}>Body ZH</label>
            <textarea
              id={`seq-body-zh-${i}`}
              className="form-control form-control-sm"
              rows={3}
              value={step.bodyZh}
              onChange={(e) => {
                const next = steps.map((s, idx) => (idx === i ? { ...s, bodyZh: e.target.value } : s));
                setSeqDraft(next);
              }}
            />
          </div>
        ))}
        <button
          type="button"
          className="btn btn-sm btn-outline-secondary mt-2 me-2"
          onClick={() => setSeqDraft([...steps, emptyStep()])}
        >
          Add step
        </button>
        <button
          type="button"
          className="btn btn-sm btn-primary mt-2"
          disabled={pipeline.saveSequence.isPending}
          onClick={() => pipeline.saveSequence.mutate({ type: seqType, body: { type: seqType, steps } })}
        >
          Save sequence
        </button>
      </AdminEditorSection>

      <AdminEditorSection title="Outreach stats">
        <p className="small mb-0">
          Sends {stats?.sent ?? 0} · bounces {(((stats?.bounceRate ?? 0) * 100).toFixed(2))}% ·
          complaints {(((stats?.complaintRate ?? 0) * 100).toFixed(3))}% · replies {stats?.replies ?? 0} ·
          cap {stats?.dailyCap ?? "—"} · breaker {stats?.breaker?.tripped ? "tripped" : "clear"}
          {stats?.identityVerified === false ? " · sending identity not verified" : ""}
          {stats?.identity?.dkimStatus ? ` · DKIM ${stats.identity.dkimStatus}` : ""}
        </p>
      </AdminEditorSection>
    </div>
  );
}

function ProspectEditor({
  prospect,
  error,
  saving,
  onDirty,
  onSave,
  onMerge,
}: {
  readonly prospect: BoardProspect;
  readonly error: string | null;
  readonly saving: boolean;
  readonly onDirty: (dirty: boolean) => void;
  readonly onSave: (body: BoardProspectWrite) => void;
  readonly onMerge: (into: string) => void;
}) {
  const [contact, setContact] = useState(prospect.contact ?? "");
  const [note, setNote] = useState(prospect.ownerNote ?? "");
  const [mergeInto, setMergeInto] = useState(prospect.possibleDuplicates?.[0]?.prospectId ?? "");
  function reportDirty(nextContact: string, nextNote: string) {
    onDirty(nextContact !== (prospect.contact ?? "") || nextNote !== (prospect.ownerNote ?? ""));
  }
  return (
    <div>
      <p className="small mb-2">
        {prospect.type} · {prospect.district} · {prospect.stage} · score {prospect.score ?? "—"}
      </p>
      <p className="small mb-2">{prospect.fitNote || "No fit note yet."}</p>
      <p className="small mb-2">
        Website: {prospect.website || "—"}
        {prospect.lastThreadId ? (
          <>
            {" · "}
            <a href={`?tab=board&section=mail`} className="link-underline">Thread {prospect.lastThreadId}</a>
          </>
        ) : null}
      </p>
      <ul className="small mb-2">
        {(prospect.touches ?? []).map((t, i) => (
          <li key={`${t.sentAt}-${i}`}>{t.subject || `Step ${t.stepIndex}`} — {(t.preview || "").slice(0, 80)}</li>
        ))}
      </ul>
      {(prospect.possibleDuplicates ?? []).length > 0 ? (
        <p className="small mb-2">Possible duplicates: {(prospect.possibleDuplicates ?? []).map((d) => d.name || d.prospectId).join(", ")}</p>
      ) : null}
      <label className="form-label small mb-1" htmlFor="pipe-contact">Contact</label>
      <input
        id="pipe-contact"
        className="form-control form-control-sm mb-2"
        value={contact}
        onChange={(e) => {
          const next = e.target.value;
          setContact(next);
          reportDirty(next, note);
        }}
      />
      <label className="form-label small mb-1" htmlFor="pipe-note">Note</label>
      <textarea
        id="pipe-note"
        className="form-control form-control-sm mb-2"
        rows={2}
        value={note}
        onChange={(e) => {
          const next = e.target.value;
          setNote(next);
          reportDirty(contact, next);
        }}
      />
      <div className="d-flex flex-wrap gap-2 mb-2">
        <button type="button" className="btn btn-primary" disabled={saving} aria-busy={saving} onClick={() => onSave({ contact, note })}>
          {saving ? (
            <>
              <span className="spinner-border spinner-border-sm me-2" aria-hidden="true" />
              Saving…
            </>
          ) : (
            "Update"
          )}
        </button>
        {OWNER_STAGES.map((s) => (
          <button key={s} type="button" className="btn btn-sm btn-outline-secondary" disabled={saving} onClick={() => onSave({ stage: s })}>
            {s === "suppressed" ? "Suppress" : s === "declined" ? "Mark declined" : s === "parked" ? "Park" : "Mark qualified"}
          </button>
        ))}
      </div>
      {(prospect.possibleDuplicates ?? []).length > 0 ? (
        <div className="d-flex gap-2 align-items-center">
          <label className="form-label small mb-0" htmlFor="pipe-merge">Merge into</label>
          <select id="pipe-merge" className="form-select form-select-sm w-auto" value={mergeInto} onChange={(e) => setMergeInto(e.target.value)}>
            {(prospect.possibleDuplicates ?? []).map((d) => (
              <option key={d.prospectId} value={d.prospectId}>{d.name || d.prospectId}</option>
            ))}
          </select>
          <button type="button" className="btn btn-sm btn-outline-danger" disabled={!mergeInto} onClick={() => onMerge(mergeInto)}>
            Merge
          </button>
        </div>
      ) : null}
      {error ? <p className="small text-danger mb-0 mt-2">{error}</p> : null}
    </div>
  );
}
