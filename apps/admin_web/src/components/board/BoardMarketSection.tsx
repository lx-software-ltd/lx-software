import { useMemo, useState } from "react";
import { AdminCell, AdminDataTable, AdminDataTableEmptyRow, AdminEditorSection, TableIconButton } from "../ui";
import { BoardTaskDrawer } from "./BoardTaskDrawer";
import { useBoardMarket } from "../../hooks/useBoardMarket";
import { useBoardTask, useBoardTasks } from "../../hooks/useBoardTasks";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import type { BoardWatch, BoardWatchWrite } from "../../lib/boardModel";
import { BOARD_STAFF_WATCH_KINDS } from "../../lib/contracts/generated";

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

const KIND_OPTIONS = BOARD_STAFF_WATCH_KINDS.filter((k) => k !== "candidate");

const WATCH_COLUMNS = [
  { key: "name", header: "Name" },
  { key: "kind", header: "Kind", priority: "secondary" as const },
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
  return { name: "", kind: "competitor", urls: [""], appIds: { ios: "", android: "" }, socialHandles: [] };
}

export function BoardMarketSection() {
  const market = useBoardMarket();
  const tasks = useBoardTasks();
  const [form, setForm] = useState<BoardWatchWrite>(emptyForm());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [briefId, setBriefId] = useState<string | null>(null);
  const [watchFilter, setWatchFilter] = useState("");
  const [candidateFilter, setCandidateFilter] = useState("");
  const briefDetail = useBoardTask(briefId);

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
      return [w.name, w.kind, ...(w.urls ?? [])].join(" ").toLowerCase().includes(q);
    });
  }, [market.watches, watchFilter]);

  const save = () => {
    const urls = (form.urls ?? []).map((u) => u.trim()).filter(Boolean);
    const body: BoardWatchWrite = {
      name: (form.name ?? "").trim(),
      kind: form.kind || "competitor",
      urls,
      appIds: {
        ...(form.appIds?.ios ? { ios: form.appIds.ios.trim() } : {}),
        ...(form.appIds?.android ? { android: form.appIds.android.trim() } : {}),
      },
      socialHandles: form.socialHandles,
    };
    if (editingId) {
      market.update.mutate(
        { watchId: editingId, body },
        {
          onSuccess: () => {
            setEditingId(null);
            setForm(emptyForm());
          },
        },
      );
    } else {
      market.add.mutate(body, { onSuccess: () => setForm(emptyForm()) });
    }
  };

  return (
    <div>
      <h2 className="h5 mb-3">Market</h2>
      <AdminEditorSection
        title={editingId ? "Edit watch" : "Add a watch"}
        description="Start with five competitors. Discovery adds candidates on Monday; promote the ones that keep showing up."
        footer={
          <>
            <button
              type="button"
              className="btn btn-primary"
              disabled={market.add.isPending || market.update.isPending}
              onClick={save}
            >
              {editingId ? "Update" : "Add"}
            </button>
            <button
              type="button"
              className="btn btn-outline-secondary"
              onClick={() => {
                setEditingId(null);
                setForm(emptyForm());
              }}
            >
              Clear
            </button>
          </>
        }
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
        {errorText(market.add.error) ?? errorText(market.update.error) ? (
          <div className="small text-danger mt-2">{errorText(market.add.error) ?? errorText(market.update.error)}</div>
        ) : null}
      </AdminEditorSection>

      <h3 className="h6 text-uppercase text-muted mt-4">Watchlist</h3>
      <AdminDataTable
        columns={WATCH_COLUMNS}
        filterValue={watchFilter}
        onFilterChange={setWatchFilter}
        filterPlaceholder="Filter watches"
      >
        {listed.length === 0 ? (
          <AdminDataTableEmptyRow colSpan={WATCH_COLUMNS.length} message="No watches yet. Add a competitor above." />
        ) : (
          listed.map((watch) => (
            <WatchRow
              key={watch.watchId}
              watch={watch}
              onEdit={() => {
                setEditingId(watch.watchId);
                setForm({
                  name: watch.name,
                  kind: watch.kind,
                  urls: [...watch.urls],
                  appIds: { ios: watch.appIds?.ios ?? "", android: watch.appIds?.android ?? "" },
                  socialHandles: watch.socialHandles,
                });
              }}
              onRemove={() => market.remove.mutate(watch.watchId)}
            />
          ))
        )}
      </AdminDataTable>

      <h3 className="h6 text-uppercase text-muted mt-4">Candidates</h3>
      <AdminDataTable
        columns={CANDIDATE_COLUMNS}
        filterValue={candidateFilter}
        onFilterChange={setCandidateFilter}
        filterPlaceholder="Filter candidates"
      >
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
                <TableIconButton
                  iconClassName="bi bi-check-lg"
                  ariaLabel={`Promote ${watch.name}`}
                  onClick={() => market.update.mutate({ watchId: watch.watchId, body: { kind: "competitor" } })}
                />
                <TableIconButton
                  iconClassName="bi bi-x-lg"
                  ariaLabel={`Ignore ${watch.name}`}
                  onClick={() => market.remove.mutate(watch.watchId)}
                />
              </AdminCell>
            </tr>
          ))
        )}
      </AdminDataTable>

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
          isMutating={tasks.review.isPending || tasks.cancel.isPending}
          errorMessage={errorText(briefDetail.error) ?? errorText(tasks.review.error)}
          onClose={() => setBriefId(null)}
          onCancel={(taskId) => tasks.cancel.mutate(taskId, { onSuccess: () => setBriefId(null) })}
          onReview={(taskId, verdict, notes) =>
            tasks.review.mutate({ taskId, verdict, notes }, { onSuccess: () => setBriefId(null) })
          }
        />
      ) : null}
    </div>
  );
}

function WatchRow({
  watch,
  onEdit,
  onRemove,
}: {
  readonly watch: BoardWatch;
  readonly onEdit: () => void;
  readonly onRemove: () => void;
}) {
  const unreadables = (watch.pages ?? []).filter((p) => p.emptyBody);
  return (
    <tr>
      <AdminCell column="name">
        {watch.name}
        {unreadables.length > 0 ? (
          <div className="small text-muted">
            not readable · {unreadables.length} page{unreadables.length === 1 ? "" : "s"}
          </div>
        ) : null}
      </AdminCell>
      <AdminCell column="kind">{watch.kind}</AdminCell>
      <AdminCell column="urls">
        <span className="small">{watch.urls.slice(0, 2).join(" · ")}</span>
      </AdminCell>
      <AdminCell column="ops">
        <TableIconButton iconClassName="bi bi-pencil" ariaLabel={`Edit ${watch.name}`} onClick={onEdit} />
        <TableIconButton iconClassName="bi bi-trash" ariaLabel={`Remove ${watch.name}`} onClick={onRemove} />
      </AdminCell>
    </tr>
  );
}
