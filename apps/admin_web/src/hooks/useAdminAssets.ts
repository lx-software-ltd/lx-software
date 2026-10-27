import { keepPreviousData, useInfiniteQuery, useQuery, type QueryClient } from "@tanstack/react-query";
import { AdminApiError, adminFetchJson, deleteAdminAsset } from "../lib/apiAdminClient";
import { keys } from "../lib/queryKeys";

export interface AdminAssetMeta {
  readonly pk: string;
  readonly sk: string;
  readonly sha256?: string;
  readonly clientSha256?: string;
  readonly size?: number;
  readonly ownerSub?: string;
  /** ISO 8601 UTC instant from S3 LastModified when the asset was confirmed. */
  readonly uploadedAt?: string;
  readonly fileName?: string;
  /** House or statement-book key when the upload was tied to a finance import. */
  readonly house?: string;
}

export function deleteAssetMutationOptions(
  qc: QueryClient,
  onDeleted?: (objectKey: string) => void,
) {
  return {
    mutationFn: (objectKey: string) => deleteAdminAsset(objectKey),
    onSuccess: (_data: void, objectKey: string) => {
      void qc.invalidateQueries({ queryKey: [...keys.admin, "asset-records"] });
      void qc.invalidateQueries({ queryKey: [...keys.admin, "asset-record"] });
      onDeleted?.(objectKey);
    },
  };
}

export function useAdminAssets(filter = "") {
  const q = filter.trim();
  return useInfiniteQuery({
    queryKey: [...keys.admin, "asset-records", q],
    placeholderData: keepPreviousData,
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (pageParam) params.set("cursor", pageParam);
      const qs = params.toString();
      const data = await adminFetchJson<{
        items: AdminAssetMeta[];
        nextCursor?: string | null;
      }>(`/assets${qs ? `?${qs}` : ""}`);
      const items = data.items.filter((row) => row.pk.startsWith("ASSET#") && row.sk === "META");
      return { items, nextCursor: data.nextCursor ?? null };
    },
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}

/** One confirmed asset for a deep link that is not on the loaded page. A 404 is a missing row. */
export function useAdminAsset(objectKey: string | null) {
  return useQuery({
    queryKey: [...keys.admin, "asset-record", objectKey],
    enabled: Boolean(objectKey),
    queryFn: async () => {
      try {
        const data = await adminFetchJson<{ item: AdminAssetMeta }>(
          `/assets?key=${encodeURIComponent(objectKey ?? "")}`,
        );
        const row = data.item;
        if (!row?.pk.startsWith("ASSET#") || row.sk !== "META") return null;
        return row;
      } catch (err) {
        if (err instanceof AdminApiError && err.status === 404) return null;
        throw err;
      }
    },
  });
}
