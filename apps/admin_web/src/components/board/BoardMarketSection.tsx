import { type FormEvent, useMemo, useState } from "react";
import {
  AdminCell,
  AdminCreateButton,
  AdminDataTable,
  AdminDataTableEmptyRow,
  AdminEditorPanel,
  AdminExpandableRow,
  AdminFilterBar,
  AdminFilterField,
  AdminRecordTable,
  AdminRowActions,
  ConfirmDialog,
} from "../ui";
import { BoardTaskDrawer } from "./BoardTaskDrawer";
import { DRAFT_RECORD_ID } from "../../lib/expandedRecord";
import { useExpandedRecord } from "../../hooks/useExpandedRecord";
import { useHydrateExpandedRecord } from "../../hooks/useHydrateExpandedRecord";
import { useBoardMarket } from "../../hooks/useBoardMarket";
import { useBoardTask, useBoardTasks } from "../../hooks/useBoardTasks";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import type { BoardWatch, BoardWatchWrite } from "../../lib/boardModel";
import { BOARD_CATALOG_DISTRICTS, BOARD_STAFF_WATCH_KINDS } from "../../lib/contracts/generated";

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

const KIND_OPTIONS = BOARD_STAFF_WATCH_KINDS.filter((k) => k !== "candidate");

const WATCH_COLUMNS = [
  { key: "name", header: "Name" },
  { key: "kind", header: "Kind", priority: "secondary" as const },
  { key: "district", header: "District", priority: "secondary" as const },
  { key: "urls", header: "Pages", priority: "secondary" as const },
  { key: "ops", header: <span className="visually-hidden">Operations</span>, className: "text-end" },
] as const;

const CANDIDATE_COLUMNS = [
  { key: "name", header: "Name" },
  { key: "url", header: "Homepage", priority: "secondary" as const },
  { key: "seen", header: "Seen", priority: "secondary" as const },
  { key: "ops", header: <span className="visually-hidden">Operations</span>, className: "text-end" },
] as const;

function emptyForm(): BoardWatchWrite {
  return { name: "", kind: "competitor", urls: [""], district: "", appIds: { ios: "", android: "" }, socialHandles: [] };
}

function watchToForm(watch: BoardWatch): BoardWatchWrite {
  return {
    name: watch.name,
    kind: watch.kind,
    urls: [...watch.urls],
    district: watch.district ?? "",
    appIds: { ios: watch.appIds?.ios ?? "", android: watch.appIds?.android ?? "" },
    socialHandles: watch.socialHandles,
  };
}

export function BoardMarketSection() {
  const market = useBoardMarket();
  const tasks = useBoardTasks();
  const expanded = useExpandedRecord("watch");
  const [form, setForm] = useState<BoardWatchWrite>(emptyForm());
  const [briefId, setBriefId] = useState<string | null>(null);
  const [watchFilter, setWatchFilter] = useState("");
  const [candidateFilter, setCandidateFilter] = useState("");
  const [pendingRemoveId, setPendingRemoveId] = useState<string | null>(null);
  const briefDetail = useBoardTask(briefId);
  const editingId =
    expanded.expandedId && expanded.expandedId !== DRAFT_RECORD_ID ? expanded.expandedId : null;
  const formOpen = expanded.expandedId !== null;

  const candidates = useMemo(() => {
    const q = candidateFilter.trim().toLowerCase();
    return market.watches.filter((w) => {
      if (w.kind !== "candidate") return false;
      if (!q) return true;
      return [w.name, ...(w.urls ?? [])].join(" ").toLowerCase().includes(q);
    });
  }, [market.watches, candidateFilter]);
  const listed = useMemo(() => {
    const q = watchFilter.trim().toLowerCase();
    return market.watches.filter((w) => {
      if (w.kind === "candidate") return false;
      if (!q) return true;
      return [w.name, w.kind, w.district, ...(w.urls ?? [])].join(" ").toLowerCase().includes(q);
    });
  }, [market.watches, watchFilter]);

  const save = () => {
    const urls = (form.urls ?? []).map((u) => u.trim()).filter(Boolean);
    const body: BoardWatchWrite = {
      name: (form.name ?? "").trim(),
      kind: form.kind || "competitor",
      urls,
      district: (form.district ?? "").trim(),
      appIds: {
        ...(form.appIds?.ios ? { ios: form.appIds.ios.trim() } : {}),
        ...(form.appIds?.android ? { android: form.appIds.android.trim() } : {}),
      },
      socialHandles: form.socialHandles,
    };
    const close = () => {
      setForm(emptyForm());
      expanded.request(null, false);
    };
    if (editingId) {
      market.update.mutate({ watchId: editingId, body }, { onSuccess: close });
    } else {
      market.add.mutate(body, { onSuccess: close });
    }
  };

  function watchDirty(): boolean {
    if (!formOpen) return false;
    if (!editingId) {
      return (form.name ?? "").trim() !== "" || (form.urls ?? []).some((url) => url.trim() !== "");
    }
    const watch = market.watches.find((row) => row.watchId === editingId);
    if (!watch) return false;
    const saved = watchToForm(watch);
    return (
      (form.name ?? "") !== (saved.name ?? "") ||
      (form.kind ?? "") !== (saved.kind ?? "") ||
      (form.district ?? "") !== (saved.district ?? "") ||
      (form.urls ?? []).join("\n") !== (saved.urls ?? []).join("\n") ||
      (form.appIds?.ios ?? "") !== (saved.appIds?.ios ?? "") ||
      (form.appIds?.android ?? "") !== (saved.appIds?.android ?? "") ||
      JSON.stringify(form.socialHandles ?? []) !== JSON.stringify(saved.socialHandles ?? [])
    );
  }

  const editingWatch = editingId
    ? (market.watches.find((row) => row.watchId === editingId) ?? null)
    : null;
  useHydrateExpandedRecord({
    expandedId: expanded.expandedId,
    recordsReady: !market.isLoading,
    record: editingWatch,
    apply: (watch) => setForm(watchToForm(watch)),
    onMissing: () => expanded.request(null, false),
  });

  function openEdit(watch: BoardWatch) {
    expanded.toggle(watch.watchId, watchDirty(), () => setForm(watchToForm(watch)), () => setForm(emptyForm()));
  }

  function openCreate() {
    if (expanded.expandedId === DRAFT_RECORD_ID) {
      expanded.request(null, watchDirty(), () => setForm(emptyForm()));
      return;
    }
    expanded.request(DRAFT_RECORD_ID, watchDirty(), () => setForm(emptyForm()));
  }

  const watchEditor = formOpen ? (
    <AdminEditorPanel
      formId="watch-form"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        save();
      }}
      submitLabel={editingId ? "Update" : "Add"}
      isSaving={market.add.isPending || market.update.isPending}
      error={errorText(market.add.error) ?? errorText(market.update.error)}
    >
      <div className="row g-2">
        <div className="col-md-6">
          <label className="form-label" htmlFor="watch-name">
            Name
          </label>
          <input
            id="watch-name"
            className="form-control"
            value={form.name ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
        </div>
        <div className="col-md-3">
          <label className="form-label" htmlFor="watch-kind">
            Kind
          </label>
          <select
            id="watch-kind"
            className="form-select"
            value={form.kind ?? "competitor"}
            onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value }))}
          >
            {KIND_OPTIONS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>
        <div className="col-md-3">
          <label className="form-label" htmlFor="watch-district">
            District
          </label>
          <select
            id="watch-district"
            className="form-select"
            value={form.district ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, district: e.target.value }))}
          >
            <option value="">Guess from URL / page</option>
            {BOARD_CATALOG_DISTRICTS.map((row) => (
              <option key={row.id} value={row.name}>
                {row.name}
              </option>
            ))}
          </select>
        </div>
        <div className="col-12">
          <label className="form-label" htmlFor="watch-urls">
            URLs (one per line)
          </label>
          <textarea
            id="watch-urls"
            className="form-control"
            rows={3}
            value={(form.urls ?? []).join("\n")}
            onChange={(e) => setForm((f) => ({ ...f, urls: e.target.value.split("\n") }))}
          />
        </div>
        <div className="col-md-6">
          <label className="form-label" htmlFor="watch-ios">
            App Store id
          </label>
          <input
            id="watch-ios"
            className="form-control"
            value={form.appIds?.ios ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, appIds: { ...f.appIds, ios: e.target.value } }))}
          />
        </div>
        <div className="col-md-6">
          <label className="form-label" htmlFor="watch-android">
            Play package
          </label>
          <input
            id="watch-android"
            className="form-control"
            value={form.appIds?.android ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, appIds: { ...f.appIds, android: e.target.value } }))}
          />
        </div>
      </div>
    </AdminEditorPanel>
  ) : null;

  return (
    <div>
      <h3 className="admin-card-title">Watchlist</h3>
      <AdminRecordTable
        label="Watchlist"
        filters={
          <AdminFilterBar create={<AdminCreateButton label="New watch" onClick={openCreate} />}>
            <AdminFilterField label="Filter" htmlFor="watch-filter">
              <input
                id="watch-filter"
                type="search"
                className="form-control form-control-sm"
                placeholder="Filter watches"
                autoComplete="off"
                value={watchFilter}
                onChange={(ev) => setWatchFilter(ev.target.value)}
              />
            </AdminFilterField>
          </AdminFilterBar>
        }
      >
      <AdminDataTable bare columns={WATCH_COLUMNS}>
        {expanded.expandedId === DRAFT_RECORD_ID ? (
          <AdminExpandableRow colSpan={WATCH_COLUMNS.length} expanded onToggle={openCreate} editor={watchEditor}>
            <AdminCell column="name">New watch</AdminCell>
            <AdminCell column="kind" />
            <AdminCell column="district" />
            <AdminCell column="urls" />
            <AdminCell column="ops" />
          </AdminExpandableRow>
        ) : null}
        {listed.length === 0 && expanded.expandedId !== DRAFT_RECORD_ID ? (
          <AdminDataTableEmptyRow colSpan={WATCH_COLUMNS.length} message="No watches yet." />
        ) : (
          listed.map((watch) => {
            const unreadables = (watch.pages ?? []).filter((page) => page.emptyBody);
            return (
              <AdminExpandableRow
                key={watch.watchId}
                colSpan={WATCH_COLUMNS.length}
                expanded={expanded.expandedId === watch.watchId}
                onToggle={() => openEdit(watch)}
                editor={watchEditor}
              >
                <AdminCell column="name">
                  {watch.name}
                  {unreadables.length > 0 ? (
                    <div className="small text-muted">
                      not readable · {unreadables.length} page{unreadables.length === 1 ? "" : "s"}
                    </div>
                  ) : null}
                </AdminCell>
                <AdminCell column="kind">{watch.kind}</AdminCell>
                <AdminCell column="district">{watch.district || "—"}</AdminCell>
                <AdminCell column="urls">
                  <span className="small">{watch.urls.slice(0, 2).join(" · ")}</span>
                </AdminCell>
                <AdminCell column="ops">
                  <AdminRowActions
                    actions={[
                      {
                        id: "edit",
                        label: `Edit ${watch.name}`,
                        iconClassName: "bi bi-pencil",
                        onClick: () => openEdit(watch),
                      },
                      {
                        id: "remove",
                        label: `Remove ${watch.name}`,
                        iconClassName: "bi bi-trash",
                        danger: true,
                        onClick: () => setPendingRemoveId(watch.watchId),
                      },
                    ]}
                  />
                </AdminCell>
              </AdminExpandableRow>
            );
          })
        )}
      </AdminDataTable>
      <ConfirmDialog
        open={pendingRemoveId !== null}
        title="Remove watch"
        body="Remove this watch from the list?"
        confirmLabel="Remove"
        tone="danger"
        confirmBusy={market.remove.isPending}
        onConfirm={() => {
          if (!pendingRemoveId) return;
          const id = pendingRemoveId;
          market.remove.mutate(id, {
            onSuccess: () => {
              setPendingRemoveId(null);
              if (expanded.expandedId === id) expanded.request(null, false);
            },
          });
        }}
        onCancel={() => {
          if (!market.remove.isPending) setPendingRemoveId(null);
        }}
      />
      </AdminRecordTable>

      <h3 className="admin-card-title mt-4">Candidates</h3>
      <AdminRecordTable
        label="Candidates"
        filters={
          <AdminFilterBar>
            <AdminFilterField label="Filter" htmlFor="candidate-filter">
              <input
                id="candidate-filter"
                type="search"
                className="form-control form-control-sm"
                placeholder="Filter candidates"
                autoComplete="off"
                value={candidateFilter}
                onChange={(ev) => setCandidateFilter(ev.target.value)}
              />
            </AdminFilterField>
          </AdminFilterBar>
        }
      >
      <AdminDataTable bare columns={CANDIDATE_COLUMNS}>
        {candidates.length === 0 ? (
          <AdminDataTableEmptyRow
            colSpan={CANDIDATE_COLUMNS.length}
            message="Weekly discovery has not added candidates yet."
          />
        ) : (
          candidates.map((watch) => (
            <tr key={watch.watchId}>
              <AdminCell column="name">{watch.name}</AdminCell>
              <AdminCell column="url">
                <span className="small">{watch.urls[0]}</span>
              </AdminCell>
              <AdminCell column="seen">{(watch.seenWeeks ?? []).length} weeks</AdminCell>
              <AdminCell column="ops">
                <AdminRowActions
                  actions={[
                    {
                      id: "promote",
                      label: `Promote ${watch.name}`,
                      iconClassName: "bi bi-check-lg",
                      onClick: () =>
                        market.update.mutate({ watchId: watch.watchId, body: { kind: "competitor" } }),
                    },
                    {
                      id: "ignore",
                      label: `Ignore ${watch.name}`,
                      iconClassName: "bi bi-x-lg",
                      danger: true,
                      onClick: () => setPendingRemoveId(watch.watchId),
                    },
                  ]}
                />
              </AdminCell>
            </tr>
          ))
        )}
      </AdminDataTable>
      </AdminRecordTable>

      <section className="card shadow-sm mb-3 mt-4">
        <div className="card-body">
          <h3 className="h6 mb-3">Change notes</h3>
          {market.changes.length === 0 ? (
            <p className="text-muted small mb-0">
              No changes this week. The 03:00 HKT crawl writes a note when a page hash changes.
            </p>
          ) : (
            <ol className="list-unstyled mb-0">
              {market.changes.map((change) => (
                <li key={change.changeId} className="border-bottom py-2">
                  <div className="small text-muted">
                    {change.kind} · {change.url}
                  </div>
                  <div>{change.summary}</div>
                  <details className="small mt-1">
                    <summary>Before / after digest</summary>
                    <div className="row g-2 mt-1">
                      <div className="col-md-6">
                        <pre className="small bg-light p-2">{change.beforeDigest || "(empty)"}</pre>
                      </div>
                      <div className="col-md-6">
                        <pre className="small bg-light p-2">{change.afterDigest || "(empty)"}</pre>
                      </div>
                    </div>
                  </details>
                </li>
              ))}
            </ol>
          )}
        </div>
      </section>

      <section className="card shadow-sm mb-3">
        <div className="card-body">
          <h3 className="h6 mb-2">Latest weekly brief</h3>
          {market.latestBrief ? (
            <button
              type="button"
              className="btn btn-link p-0"
              onClick={() => setBriefId(market.latestBrief?.taskId ?? null)}
            >
              {market.latestBrief.summary || market.latestBrief.eventRef?.id || market.latestBrief.taskId}
            </button>
          ) : (
            <p className="text-muted small mb-0">No brief yet. Monday 04:00 HKT creates a market-analyst duty.</p>
          )}
        </div>
      </section>

      {briefId ? (
        <BoardTaskDrawer
          detail={briefDetail.data}
          isLoading={briefDetail.isLoading}
          isMutating={tasks.review.isPending || tasks.cancel.isPending || tasks.retry.isPending}
          errorMessage={
            errorText(briefDetail.error) ??
            errorText(tasks.cancel.error) ??
            errorText(tasks.review.error) ??
            errorText(tasks.retry.error)
          }
          onClose={() => setBriefId(null)}
          onCancel={(taskId) => tasks.cancel.mutate(taskId, { onSuccess: () => setBriefId(null) })}
          onReview={(taskId, verdict, notes) =>
            tasks.review.mutate({ taskId, verdict, notes }, { onSuccess: () => setBriefId(null) })
          }
          onRetry={(taskId) => tasks.retry.mutate(taskId)}
        />
      ) : null}
    </div>
  );
}
