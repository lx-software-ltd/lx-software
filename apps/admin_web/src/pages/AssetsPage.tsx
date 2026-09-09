import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  AdminCell,
  AdminPageIntro,
  AdminDataTable,
  AdminDataTableCellMeta,
  AdminDataTableEmptyRow,
  TableIconButton,
} from "../components/ui";
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

function AssetOpenLink({
  objectKey,
  onError,
}: {
  readonly objectKey: string;
  readonly onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const open = async () => {
    setBusy(true);
    try {
      const qs = `?key=${encodeURIComponent(objectKey)}`;
      const { url } = await adminFetchJson<{ url: string }>(
        `/assets/download-url${qs}`,
      );
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      onError(
        getAdminApiErrorMessage(err) ??
          "Could not open the file. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <TableIconButton
      iconClassName="bi bi-box-arrow-up-right"
      ariaLabel="Open file in new tab"
      onClick={() => void open()}
      disabled={busy}
    />
  );
}

const ASSET_TABLE_COLUMNS = [
  { key: "uploaded", header: "Uploaded", priority: "secondary" as const },
  { key: "file", header: "File" },
  { key: "entity", header: "Entity", priority: "secondary" as const },
  { key: "actions", header: "Actions", className: "text-end admin-nowrap" },
] as const;

function AssetDeleteButton({
  objectKey,
  label,
  onError,
}: {
  readonly objectKey: string;
  readonly label: string;
  readonly onError: (message: string) => void;
}) {
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => deleteAdminAsset(objectKey),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "asset-records"] });
    },
  });
  const onClick = () => {
    if (
      !window.confirm(
        `Delete “${label}” from storage? Any statement lines that still reference this key will need to be edited.`,
      )
    ) {
      return;
    }
    void del.mutateAsync().catch((err: unknown) => {
      const detail = getAdminApiErrorMessage(err);
      onError(
        detail ??
          (err instanceof AdminApiError
            ? `Delete failed (${err.status}).`
            : "Could not delete the file. Try again."),
      );
    });
  };
  return (
    <TableIconButton
      iconClassName="bi bi-trash"
      ariaLabel="Delete file from storage"
      variant="danger"
      onClick={onClick}
      disabled={del.isPending}
    />
  );
}

export function AssetsPage() {
  const q = useAdminAssets();
  const [tableFilter, setTableFilter] = useState("");
  const [pageError, setPageError] = useState<string | null>(null);

  const rows = useMemo(
    () => q.data?.pages.flatMap((p) => p.items) ?? [],
    [q.data],
  );

  const displayRows = useMemo(() => {
    const sorted = [...rows].sort(
      (a, b) =>
        uploadedAtSortMs(b.uploadedAt) - uploadedAtSortMs(a.uploadedAt),
    );
    return sorted.filter((row) => rowMatchesFilter(row, tableFilter));
  }, [rows, tableFilter]);

  useEffect(() => {
    if (q.hasNextPage && !q.isFetchingNextPage && !q.isError) {
      void q.fetchNextPage();
    }
  }, [q.hasNextPage, q.isFetchingNextPage, q.isError, q.fetchNextPage]);

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
          <AdminDataTable
            columns={ASSET_TABLE_COLUMNS}
            filterValue={tableFilter}
            onFilterChange={(v) => {
              setTableFilter(v);
              setPageError(null);
            }}
            filterPlaceholder="Filter by file or entity…"
          >
            {displayRows.length ? (
              displayRows.map((row) => {
                const objectKey = objectKeyFromAssetPk(row.pk);
                return (
                  <tr key={row.pk}>
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
                    <AdminCell column="actions" className="text-end">
                      <div className="d-inline-flex align-items-center gap-1">
                        <AssetOpenLink
                          objectKey={objectKey}
                          onError={setPageError}
                        />
                        <AssetDeleteButton
                          objectKey={objectKey}
                          label={displayFileName(row)}
                          onError={setPageError}
                        />
                      </div>
                    </AdminCell>
                  </tr>
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
          {q.isFetchingNextPage ? (
            <p className="text-muted small mt-2 mb-0">Loading more…</p>
          ) : null}
        </>
      )}
    </div>
  );
}
