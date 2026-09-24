import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  AdminCell,
  AdminPageIntro,
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
  useAdminAssets,
  type AdminAssetMeta,
} from "../hooks/useAdminAssets";
import {
  AdminApiError,
  adminFetchJson,
  deleteAdminAsset,
  getAdminApiErrorMessage,
} from "../lib/apiAdminClient";
import { formatFileSizeBytes, objectKeyFromAssetPk } from "../lib/adminAssets";
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
  const entityKey = (row.house ?? "").toLowerCase();
  const entityDisplay = houseDisplayLabel(row.house).toLowerCase();
  return (
    file.includes(q) || entityKey.includes(q) || entityDisplay.includes(q)
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
  const q = useAdminAssets();
  const qc = useQueryClient();
  const expanded = useExpandedRecord("asset");
  const [tableFilter, setTableFilter] = useState("");
  const [pageError, setPageError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<AdminAssetMeta | null>(null);
  const [openingKey, setOpeningKey] = useState<string | null>(null);
  const del = useMutation({
    mutationFn: (objectKey: string) => deleteAdminAsset(objectKey),
    onSuccess: (_data, objectKey) => {
      void qc.invalidateQueries({ queryKey: ["admin", "asset-records"] });
      setPendingDelete(null);
      if (expanded.expandedId && objectKeyFromAssetPk(expanded.expandedId) === objectKey) {
        expanded.request(null, false);
      }
    },
  });

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
  const openAssetRow = expanded.expandedId
    ? (rows.find((row) => row.pk === expanded.expandedId) ?? null)
    : null;
  useHydrateExpandedRecord({
    expandedId: expanded.expandedId,
    recordsReady: !q.isLoading && !q.hasNextPage && !q.isFetchingNextPage,
    record: openAssetRow,
    apply: () => undefined,
    onMissing: () => expanded.request(null, false),
  });

  const displayRows = useMemo(() => {
    const sorted = [...rows].sort(
      (a, b) =>
        uploadedAtSortMs(b.uploadedAt) - uploadedAtSortMs(a.uploadedAt),
    );
    return sorted.filter((row) => rowMatchesFilter(row, tableFilter));
  }, [rows, tableFilter]);

  const { hasNextPage, isFetchingNextPage, isError, fetchNextPage } = q;
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && !isError) {
      void fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, isError, fetchNextPage]);

  return (
    <div>
      <h1 className="h3 mb-3">Assets</h1>
      <AdminPageIntro>
        Statement uploads and other files stored in the admin assets bucket;
        metadata is stored in DynamoDB (<code>ASSET#</code> keys).
      </AdminPageIntro>
      {q.isLoading ? (
        <p className="text-muted">Loading…</p>
      ) : q.isError ? (
        <div className="alert alert-danger" role="alert">
          Failed to load assets.
        </div>
      ) : (
        <>
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
          <AdminDataTable bare columns={ASSET_TABLE_COLUMNS}>
            {displayRows.length ? (
              displayRows.map((row) => {
                const objectKey = objectKeyFromAssetPk(row.pk);
                return (
                  <AdminExpandableRow
                    key={row.pk}
                    colSpan={ASSET_TABLE_COLUMNS.length}
                    expanded={expanded.expandedId === row.pk}
                    onToggle={() => expanded.toggle(row.pk, false, () => undefined, () => undefined)}
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
                message={
                  rows.length
                    ? "No assets match the filter."
                    : "No confirmed assets yet."
                }
              />
            )}
          </AdminDataTable>
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
          {isFetchingNextPage ? (
            <p className="text-muted small mt-2 mb-0">Loading more…</p>
          ) : null}
        </>
      )}
    </div>
  );
}
