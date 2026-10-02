import { useInfiniteQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { objectKeyFromAssetPk } from "../lib/adminAssets";
import { adminFetchJson, deleteAdminAsset } from "../lib/apiAdminClient";
import { keys } from "../lib/queryKeys";
import {
  FINANCE_STATEMENT_BOOK_KEYS,
  statementLineAssetKeys,
  type FinancePersistedState,
  type HouseFinanceData,
  type HouseKey,
} from "../lib/financeModel";

const HOUSE_KEYS: readonly HouseKey[] = ["hillmarton", "morrison"];

function inferHouseFromFinanceLines(
  objectKey: string,
  finance: FinancePersistedState | undefined,
): HouseKey | undefined {
  if (!finance) return undefined;
  for (const hk of HOUSE_KEYS) {
    for (const line of finance[hk].lines) {
      if (statementLineAssetKeys(line).some((k) => k === objectKey)) return hk;
    }
  }
  return undefined;
}

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
      onDeleted?.(objectKey);
    },
  };
}

export function useAdminAssets() {
  const qc = useQueryClient();
  const financeUpdatedAt = qc.getQueryState(keys.finance)?.dataUpdatedAt ?? 0;
  const bookUpdatedAt = FINANCE_STATEMENT_BOOK_KEYS.map(
    (key) => qc.getQueryState(keys.book(key))?.dataUpdatedAt ?? 0,
  );
  return useInfiniteQuery({
    queryKey: [...keys.admin, "asset-records", financeUpdatedAt, ...bookUpdatedAt],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => {
      const qs = pageParam
        ? `?cursor=${encodeURIComponent(pageParam)}`
        : "";
      const data = await adminFetchJson<{
        items: AdminAssetMeta[];
        nextCursor?: string | null;
      }>(`/assets${qs}`);
      const finance = qc.getQueryData<FinancePersistedState>(keys.finance);
      const books = FINANCE_STATEMENT_BOOK_KEYS.map((key) => ({
        key,
        data: qc.getQueryData<HouseFinanceData>(keys.book(key)),
      }));
      const items = data.items
        .filter(
          (row) => row.pk.startsWith("ASSET#") && row.sk === "META",
        )
        .map((row) => {
          if (row.house?.trim()) return row;
          const objectKey = objectKeyFromAssetPk(row.pk);
          const inferred = inferHouseFromFinanceLines(objectKey, finance);
          if (inferred) return { ...row, house: inferred };
          for (const book of books) {
            if (
              book.data?.lines.some((line) =>
                statementLineAssetKeys(line).some((k) => k === objectKey),
              )
            ) {
              return { ...row, house: book.key };
            }
          }
          return row;
        });
      return { items, nextCursor: data.nextCursor ?? null };
    },
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
