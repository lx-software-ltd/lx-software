import { useEffect, useMemo, useState } from "react";
import {
  AdminCell,
  AdminDataTable,
  AdminDataTableCellMeta,
  AdminDataTableEmptyRow,
  AdminEditorSection,
} from "../ui";
import { useBoardContent } from "../../hooks/useBoardContent";
import { adminFetchJson, getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import { boardContentCreativePath, canDeletePost, type BoardContentItem } from "../../lib/boardModel";

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

const COLUMNS = [
  { key: "slot", header: "Slot" },
  { key: "channel", header: "Channel" },
  { key: "pillar", header: "Pillar", priority: "secondary" as const },
  { key: "status", header: "Status" },
];

const GRID_CHANNELS = ["facebook", "instagram", "instagram_story", "assisted_xiaohongshu", "assisted_fb_group"];

function twoWeekDays(): string[] {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return Array.from({ length: 14 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d.toISOString().slice(0, 10);
  });
}

export function BoardContentSection() {
  const calendar = useBoardContent();
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = calendar.items.find((i) => i.contentId === selectedId) ?? null;
  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return calendar.items.filter((i) => {
      if (!q) return true;
      return [i.channel, i.pillar, i.status, i.copyEn, i.copyZh].join(" ").toLowerCase().includes(q);
    });
  }, [calendar.items, filter]);
  const days = useMemo(() => twoWeekDays(), []);
  const channels = useMemo(() => {
    const extra = calendar.items.map((i) => i.channel || "").filter(Boolean);
    return [...new Set([...GRID_CHANNELS, ...extra])];
  }, [calendar.items]);

  return (
    <div className="d-flex flex-column gap-3">
      <div className="table-responsive">
        <table className="table table-sm table-bordered admin-table-compact mb-0">
          <thead>
            <tr>
              <th scope="col">Channel</th>
              {days.map((day) => (
                <th key={day} scope="col" className="small">{day.slice(5)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {channels.map((channel) => (
              <tr key={channel}>
                <th scope="row" className="small">{channel}</th>
                {days.map((day) => {
                  const cell = calendar.items.filter(
                    (i) => i.channel === channel && (i.slotAt || "").startsWith(day),
                  );
                  return (
                    <td key={`${channel}-${day}`} className="small">
                      {cell.map((item) => (
                        <button
                          key={item.contentId}
                          type="button"
                          className="btn btn-link btn-sm p-0 d-block text-start"
                          onClick={() => setSelectedId(item.contentId)}
                        >
                          {(item.copyEn || item.copyZh || item.status || "item").slice(0, 24)}
                        </button>
                      ))}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <AdminDataTable columns={COLUMNS} filterValue={filter} onFilterChange={setFilter} filterPlaceholder="Filter items">
        {filtered.length === 0 ? (
          <AdminDataTableEmptyRow colSpan={COLUMNS.length} message="No calendar items." />
        ) : (
          filtered.map((item) => (
            <tr key={item.contentId} className={selectedId === item.contentId ? "table-active" : undefined}>
              <AdminCell column="slot">
                <button type="button" className="btn btn-link btn-sm p-0" onClick={() => setSelectedId(item.contentId)}>
                  {item.slotAt?.slice(0, 16) || "—"}
                </button>
                <AdminDataTableCellMeta>
                  {item.channel} · {item.status}
                </AdminDataTableCellMeta>
              </AdminCell>
              <AdminCell column="channel">{item.channel}</AdminCell>
              <AdminCell column="pillar">{item.pillar}</AdminCell>
              <AdminCell column="status">{item.status}</AdminCell>
            </tr>
          ))
        )}
      </AdminDataTable>
      {selected ? (
        <ContentDrawer
          key={selected.contentId}
          item={selected}
          error={errorText(calendar.update.error) ?? errorText(calendar.deletePost.error)}
          busy={calendar.deletePost.isPending}
          onClose={() => setSelectedId(null)}
          onSave={(body) => calendar.update.mutate({ contentId: selected.contentId, body })}
          onRender={() => calendar.render.mutate(selected.contentId)}
          onDeletePost={() => calendar.deletePost.mutate(selected.contentId)}
        />
      ) : null}
      <AdminEditorSection title="Assisted packs">
        {calendar.assisted.length === 0 ? (
          <p className="small text-muted mb-0">Nothing waiting to be posted by hand.</p>
        ) : (
          calendar.assisted.map((item) => (
            <div key={item.contentId} className="border rounded p-2 mb-2">
              <div className="small fw-semibold">{item.channel} · {item.slotAt?.slice(0, 16)}</div>
              <p className="small mb-1">{item.copyZh || item.copyEn}</p>
              <button
                type="button"
                className="btn btn-sm btn-outline-primary"
                onClick={() => calendar.update.mutate({ contentId: item.contentId, body: { status: "published" } })}
              >
                Mark posted
              </button>
            </div>
          ))
        )}
      </AdminEditorSection>
    </div>
  );
}

export function ContentDrawer({
  item,
  error,
  busy = false,
  onClose,
  onSave,
  onRender,
  onDeletePost,
}: {
  readonly item: BoardContentItem;
  readonly error: string | null;
  readonly busy?: boolean;
  readonly onClose: () => void;
  readonly onSave: (body: Record<string, unknown>) => void;
  readonly onRender: () => void;
  readonly onDeletePost: () => void;
}) {
  const [copyEn, setCopyEn] = useState(item.copyEn ?? "");
  const [copyZh, setCopyZh] = useState(item.copyZh ?? "");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  useEffect(() => {
    if (!item.creativeKeys?.length) {
      return;
    }
    let cancelled = false;
    void adminFetchJson<{ url: string }>(boardContentCreativePath(item.contentId, 0))
      .then((res) => {
        if (!cancelled) setPreviewUrl(res.url);
      })
      .catch(() => {
        if (!cancelled) setPreviewUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [item.contentId, item.creativeKeys]);
  return (
    <div className="border rounded p-3 bg-body-secondary">
      <div className="d-flex justify-content-between">
        <h3 className="h6 mb-0">{item.channel} · {item.pillar}</h3>
        <button type="button" className="btn-close" aria-label="Close item" onClick={onClose} />
      </div>
      <p className="small mb-2">
        Slot {item.slotAt} · {item.status}
        {item.holdId ? ` · hold ${item.holdId}` : ""}
        {item.platformPostId ? ` · post ${item.platformPostId}` : ""}
        {item.deletedPostId ? ` · deleted post ${item.deletedPostId}` : ""}
      </p>
      {previewUrl ? (
        <img src={previewUrl} alt="Creative preview" className="img-fluid rounded mb-2" style={{ maxWidth: 240 }} />
      ) : null}
      <label className="form-label small" htmlFor="c-en">Copy EN</label>
      <textarea id="c-en" className="form-control form-control-sm mb-2" rows={3} value={copyEn} onChange={(e) => setCopyEn(e.target.value)} />
      <label className="form-label small" htmlFor="c-zh">Copy ZH</label>
      <textarea id="c-zh" className="form-control form-control-sm mb-2" rows={3} value={copyZh} onChange={(e) => setCopyZh(e.target.value)} />
      <div className="d-flex flex-wrap gap-2">
        <button type="button" className="btn btn-sm btn-primary" onClick={() => onSave({ copyEn, copyZh })}>Save copy</button>
        <button type="button" className="btn btn-sm btn-outline-secondary" onClick={onRender}>Re-render</button>
        <button type="button" className="btn btn-sm btn-outline-danger" onClick={() => onSave({ status: "vetoed" })}>Veto</button>
        {canDeletePost(item) && !confirmDelete ? (
          <button type="button" className="btn btn-sm btn-danger" onClick={() => setConfirmDelete(true)}>Delete post</button>
        ) : null}
      </div>
      {canDeletePost(item) && confirmDelete ? (
        <div className="alert alert-warning small mt-2 mb-0 d-flex flex-wrap align-items-center gap-2">
          <span>
            {item.channel === "facebook"
              ? "Removes the post from the Facebook Page and marks this item vetoed."
              : "Instagram does not allow deleting through the API. Delete it in the app, then veto this item."}
          </span>
          {item.channel === "facebook" ? (
            <button type="button" className="btn btn-sm btn-danger" disabled={busy} onClick={onDeletePost}>Confirm delete</button>
          ) : null}
          <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => setConfirmDelete(false)}>Cancel</button>
        </div>
      ) : null}
      {item.performance ? <pre className="small mt-2 mb-0">{JSON.stringify(item.performance, null, 2)}</pre> : null}
      {error ? <p className="small text-danger mt-2 mb-0">{error}</p> : null}
    </div>
  );
}
