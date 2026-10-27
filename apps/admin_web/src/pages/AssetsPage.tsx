import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import {
  AdminCell,
  AdminDataTable,
  AdminDataTableCellMeta,
  AdminDataTableEmptyRow,
  AdminExpandableRow,
  AdminField,
  AdminFieldGrid,
  AdminFilterBar,
  AdminFilterField,
  AdminRecordTable,
  AdminRowActions,
  ConfirmDialog,
} from "../components/ui";
import { useExpandedRecord } from "../hooks/useExpandedRecord";
import { useHydrateExpandedRecord } from "../hooks/useHydrateExpandedRecord";
import { clearExpandedParamsExcept } from "../lib/expandedRecord";
import {
  deleteAssetMutationOptions,
  useAdminAsset,
  useAdminAssets,
  type AdminAssetMeta,
} from "../hooks/useAdminAssets";
import {
  AdminApiError,
  adminFetchJson,
  getAdminApiErrorMessage,
} from "../lib/apiAdminClient";
import { formatFileSizeBytes, objectKeyFromAssetPk } from "../lib/adminAssets";
import { keys } from "../lib/queryKeys";
import { formatDateTimeHKT } from "../lib/formatDisplay";
import { houseDisplayLabel } from "../lib/houses";

function displayFileName(row: AdminAssetMeta): string {
  const n = row.fileName?.trim();
  if (n) return n;
  const key = objectKeyFromAssetPk(row.pk);
  const parts = key.split("/");
  return parts[parts.length - 1] || key;
}

function formatUploadedInstant(iso?: string): string {
  if (!iso?.trim()) return "—";
  return formatDateTimeHKT(iso);
}

function uploadedAtSortMs(iso?: string): number {
  if (!iso?.trim()) return Number.NEGATIVE_INFINITY;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? Number.NEGATIVE_INFINITY : t;
}

function rowMatchesFilter(
  row: AdminAssetMeta,
  filterText: string,
): boolean {
  const q = filterText.trim().toLowerCase();
  if (!q) return true;
  const file = displayFileName(row).toLowerCase();
  const objectKey = objectKeyFromAssetPk(row.pk).toLowerCase();
  const entityKey = (row.house ?? "").toLowerCase();
  const entityDisplay = houseDisplayLabel(row.house).toLowerCase();
  return (
    file.includes(q) ||
    objectKey.includes(q) ||
    entityKey.includes(q) ||
    entityDisplay.includes(q)
  );
}

const ASSET_TABLE_COLUMNS = [
  { key: "uploaded", header: "Uploaded", priority: "secondary" as const },
  { key: "file", header: "File" },
  { key: "entity", header: "Entity", priority: "secondary" as const },
  {
    key: "ops",
    header: <span className="visually-hidden">Operations</span>,
    className: "text-end admin-nowrap",
  },
] as const;

function assetFieldId(pk: string, field: string): string {
  return `asset-${field}-${pk.replace(/[^A-Za-z0-9_-]/g, "_")}`;
}

/** Row parameter is the object key. Older links may still carry the `ASSET#` pk. */
function sameAsset(expandedId: string | null, pk: string): boolean {
  if (!expandedId) return false;
  return expandedId === pk || expandedId === objectKeyFromAssetPk(pk);
}

function AssetDetails({ row }: { readonly row: AdminAssetMeta }) {
  const objectKey = objectKeyFromAssetPk(row.pk);
  return (
    <AdminFieldGrid columns={2}>
      <AdminField span={2}>
        <label className="form-label small" htmlFor={assetFieldId(row.pk, "key")}>
          Object key
        </label>
        <input
          id={assetFieldId(row.pk, "key")}
          type="text"
          className="form-control form-control-sm"
          readOnly
          value={objectKey}
        />
      </AdminField>
      <AdminField>
        <label className="form-label small" htmlFor={assetFieldId(row.pk, "size")}>
          Size
        </label>
        <input
          id={assetFieldId(row.pk, "size")}
          type="text"
          className="form-control form-control-sm"
          readOnly
          value={typeof row.size === "number" ? formatFileSizeBytes(row.size) : "—"}
        />
      </AdminField>
      <AdminField>
        <label className="form-label small" htmlFor={assetFieldId(row.pk, "house")}>
          Entity
        </label>
        <input
          id={assetFieldId(row.pk, "house")}
          type="text"
          className="form-control form-control-sm"
          readOnly
          value={houseDisplayLabel(row.house)}
        />
      </AdminField>
      <AdminField span={2}>
        <label className="form-label small" htmlFor={assetFieldId(row.pk, "uploaded")}>
          Uploaded
        </label>
        <input
          id={assetFieldId(row.pk, "uploaded")}
          type="text"
          className="form-control form-control-sm"
          readOnly
          value={formatUploadedInstant(row.uploadedAt)}
        />
      </AdminField>
    </AdminFieldGrid>
  );
}

export function AssetsPage() {
  const qc = useQueryClient();
  const expanded = useExpandedRecord("asset");
  const [tableFilter, setTableFilter] = useState("");
  const debouncedFilter = useDebouncedValue(tableFilter.trim(), 300);
  const q = useAdminAssets(debouncedFilter);
  const [pageError, setPageError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<AdminAssetMeta | null>(null);
  const [openingKey, setOpeningKey] = useState<string | null>(null);
  const [pinned, setPinned] = useState<AdminAssetMeta | null>(null);
  const del = useMutation(
    deleteAssetMutationOptions(qc, (objectKey) => {
      setPendingDelete(null);
      setPinned((current) =>
        current && objectKeyFromAssetPk(current.pk) === objectKey ? null : current,
      );
      if (expanded.expandedId && objectKeyFromAssetPk(expanded.expandedId) === objectKey) {
        expanded.request(null, false);
      }
    }),
  );

  const openAsset = async (objectKey: string) => {
    setOpeningKey(objectKey);
    try {
      const qs = `?key=${encodeURIComponent(objectKey)}`;
      const { url } = await adminFetchJson<{ url: string }>(`/assets/download-url${qs}`);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setPageError(
        getAdminApiErrorMessage(err) ??
          "Could not open the file. Check your connection and try again.",
      );
    } finally {
      setOpeningKey(null);
    }
  };

  const rows = useMemo(
    () => q.data?.pages.flatMap((p) => p.items) ?? [],
    [q.data],
  );
  useEffect(() => {
    clearExpandedParamsExcept("asset");
  }, []);
  const expandedKey = expanded.expandedId
    ? objectKeyFromAssetPk(expanded.expandedId)
    : null;
  const expandedOnPage = expanded.expandedId
    ? rows.some((row) => sameAsset(expanded.expandedId, row.pk))
    : false;
  const needLinkedAsset = Boolean(expandedKey) && !q.isLoading && !expandedOnPage;
  const linked = useAdminAsset(needLinkedAsset ? expandedKey : null);
  const openAssetRow = expanded.expandedId
    ? (rows.find((row) => sameAsset(expanded.expandedId, row.pk)) ??
      (linked.data && sameAsset(expanded.expandedId, linked.data.pk) ? linked.data : null))
    : null;
  const linkedSettled = !needLinkedAsset || (linked.isFetched && !linked.isError);
  useHydrateExpandedRecord({
    expandedId: expanded.expandedId,
    recordsReady: !q.isLoading && linkedSettled,
    record: openAssetRow,
    apply: () => undefined,
    onMissing: () => expanded.request(null, false),
  });

  const displayRows = useMemo(() => {
    const offPage = [linked.data, pinned].find(
      (row): row is AdminAssetMeta => Boolean(row) && !rows.some((loaded) => loaded.pk === row?.pk),
    );
    const sorted = [...rows, ...(offPage ? [offPage] : [])].sort(
      (a, b) => uploadedAtSortMs(b.uploadedAt) - uploadedAtSortMs(a.uploadedAt),
    );
    return sorted.filter((row) => rowMatchesFilter(row, tableFilter));
  }, [rows, linked.data, pinned, tableFilter]);

  const loadMore = () => {
    void q.fetchNextPage().then((result) => {
      if (!(result.error instanceof AdminApiError) || result.error.status !== 400) return;
      setPageError("The asset list was refreshed. Load more again for older files.");
      void qc.resetQueries({ queryKey: [...keys.admin, "asset-records"] });
    });
  };

  const emptyMessage = !rows.length && !pinned && !tableFilter.trim()
    ? "No confirmed assets yet."
    : q.isFetching && !displayRows.length
      ? "Searching…"
      : q.hasNextPage
        ? "No matches yet. Load more to keep searching."
        : "No assets match the filter.";

  return (
    <div>
      {pageError ? (
            <div
              className="alert alert-danger alert-dismissible py-2 small mb-3"
              role="alert"
            >
              <button
                type="button"
                className="btn-close"
                aria-label="Dismiss"
                onClick={() => setPageError(null)}
              />
              {pageError}
            </div>
          ) : null}
      {linked.isError ? (
        <div className="alert alert-danger py-2 small mb-3" role="alert">
          Could not open that asset. The link stays in the address bar.
        </div>
      ) : null}
          <AdminRecordTable
            label="Assets"
            filters={
              <AdminFilterBar>
                <AdminFilterField label="Filter" htmlFor="assets-filter">
                  <input
                    id="assets-filter"
                    type="search"
                    className="form-control form-control-sm"
                    placeholder="Filter by file or entity…"
                    autoComplete="off"
                    value={tableFilter}
                    onChange={(ev) => {
                      setTableFilter(ev.target.value);
                      setPageError(null);
                    }}
                  />
                </AdminFilterField>
              </AdminFilterBar>
            }
          >
          {q.isLoading ? (
            <p className="text-muted">Loading…</p>
          ) : q.isError && rows.length === 0 ? (
            <div className="alert alert-danger" role="alert">
              Failed to load assets.
            </div>
          ) : (
          <AdminDataTable bare columns={ASSET_TABLE_COLUMNS}>
            {displayRows.length ? (
              displayRows.map((row) => {
                const objectKey = objectKeyFromAssetPk(row.pk);
                return (
                  <AdminExpandableRow
                    key={row.pk}
                    colSpan={ASSET_TABLE_COLUMNS.length}
                    expanded={sameAsset(expanded.expandedId, row.pk)}
                    onToggle={() => {
                      const current = expanded.expandedId;
                      const open = Boolean(current && sameAsset(current, row.pk));
                      if (open && !rows.some((loaded) => loaded.pk === row.pk)) setPinned(row);
                      expanded.toggle(open && current ? current : objectKey, false, () => undefined, () => undefined);
                    }}
                    editor={<AssetDetails row={row} />}
                  >
                    <AdminCell column="uploaded" className="small">
                      {formatUploadedInstant(row.uploadedAt)}
                    </AdminCell>
                    <AdminCell column="file">
                      <div className="fw-medium">{displayFileName(row)}</div>
                      {typeof row.size === "number" ? (
                        <div className="text-muted small">
                          {formatFileSizeBytes(row.size)}
                        </div>
                      ) : null}
                      <AdminDataTableCellMeta>
                        {houseDisplayLabel(row.house)}
                        {row.uploadedAt ? ` · ${formatUploadedInstant(row.uploadedAt)}` : ""}
                      </AdminDataTableCellMeta>
                    </AdminCell>
                    <AdminCell column="entity" className="small">{houseDisplayLabel(row.house)}</AdminCell>
                    <AdminCell column="ops" className="text-end">
                      <AdminRowActions
                        actions={[
                          {
                            id: "open",
                            label: "Open file in new tab",
                            iconClassName: "bi bi-box-arrow-up-right",
                            disabled: openingKey === objectKey,
                            onClick: () => void openAsset(objectKey),
                          },
                          {
                            id: "delete",
                            label: "Delete file from storage",
                            iconClassName: "bi bi-trash",
                            danger: true,
                            disabled: del.isPending,
                            onClick: () => setPendingDelete(row),
                          },
                        ]}
                      />
                    </AdminCell>
                  </AdminExpandableRow>
                );
              })
            ) : (
              <AdminDataTableEmptyRow
                colSpan={ASSET_TABLE_COLUMNS.length}
                message={emptyMessage}
              />
            )}
          </AdminDataTable>
          )}
          <ConfirmDialog
            open={pendingDelete !== null}
            title="Delete file"
            body={
              pendingDelete
                ? `Delete “${displayFileName(pendingDelete)}” from storage? Any statement lines that still reference this key will need to be edited.`
                : ""
            }
            confirmLabel="Delete"
            tone="danger"
            confirmBusy={del.isPending}
            onConfirm={() => {
              if (!pendingDelete) return;
              const objectKey = objectKeyFromAssetPk(pendingDelete.pk);
              void del.mutateAsync(objectKey).catch((err: unknown) => {
                const detail = getAdminApiErrorMessage(err);
                setPageError(
                  detail ??
                    (err instanceof AdminApiError
                      ? `Delete failed (${err.status}).`
                      : "Could not delete the file. Try again."),
                );
                setPendingDelete(null);
              });
            }}
            onCancel={() => {
              if (!del.isPending) setPendingDelete(null);
            }}
          />
          </AdminRecordTable>
          {q.hasNextPage ? (
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm mt-2"
              disabled={q.isFetchingNextPage}
              onClick={loadMore}
            >
              {q.isFetchingNextPage ? "Loading…" : "Load more"}
            </button>
          ) : null}
    </div>
  );
}
