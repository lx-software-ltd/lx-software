import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  boardCatalogBulkImportPath,
  boardCatalogBulkPreviewPath,
  boardCatalogCandidateDecidePath,
  boardCatalogCandidatesBulkPath,
  boardCatalogCandidatesPath,
  boardCatalogDiscoveryRunPath,
  boardCatalogSourcesPath,
  type BoardCatalogCandidate,
  type BoardCatalogCandidateQuery,
  type BoardCatalogSourcesPayload,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";
import { BOARD_PROGRESS_KEY } from "./useBoardProgress";

export const BOARD_CATALOG_SOURCES_KEY = [...BOARD_QUERY_KEY, "catalog-sources"] as const;
export const BOARD_CATALOG_CANDIDATES_KEY = [...BOARD_QUERY_KEY, "catalog-candidates"] as const;

export type BoardCatalogCandidateFilters = Omit<BoardCatalogCandidateQuery, "cursor" | "limit">;

export type BoardCatalogCandidatePage = {
  readonly candidates: readonly BoardCatalogCandidate[];
  readonly nextCursor?: number | null;
  readonly total?: number;
};

export type BoardCatalogBulkDecision = {
  readonly decision: "approve" | "reject" | "close";
  readonly source?: string;
  readonly status?: string;
  readonly before?: string;
  readonly district?: string;
  readonly q?: string;
  readonly missingPlaceId?: boolean;
};

function invalidateCatalog(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: BOARD_CATALOG_SOURCES_KEY });
  void qc.invalidateQueries({ queryKey: BOARD_CATALOG_CANDIDATES_KEY });
  void qc.invalidateQueries({ queryKey: BOARD_PROGRESS_KEY });
}

export function useBoardCatalogSources() {
  return useQuery({
    queryKey: BOARD_CATALOG_SOURCES_KEY,
    queryFn: () => adminFetchJson<BoardCatalogSourcesPayload>(boardCatalogSourcesPath()),
    refetchInterval: 30_000,
  });
}

export function useBoardCatalogCandidates(filters: string | BoardCatalogCandidateFilters = "new") {
  const resolved: BoardCatalogCandidateFilters = typeof filters === "string" ? { status: filters } : filters;
  const q = useInfiniteQuery({
    queryKey: [...BOARD_CATALOG_CANDIDATES_KEY, resolved],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      adminFetchJson<BoardCatalogCandidatePage>(
        boardCatalogCandidatesPath({ ...resolved, cursor: pageParam }),
      ),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
  return {
    ...q,
    data: q.data?.pages.flatMap((page) => page.candidates) ?? [],
    total: q.data?.pages[0]?.total ?? 0,
  };
}

export function catalogDecideMutationOptions(qc: QueryClient) {
  return {
    mutationFn: ({ candidateId, decision }: { candidateId: string; decision: "approve" | "reject" }) =>
      adminFetchJson<{ candidate: BoardCatalogCandidate }>(boardCatalogCandidateDecidePath(candidateId, decision), {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => invalidateCatalog(qc),
  };
}

export function catalogBulkDecideMutationOptions(qc: QueryClient) {
  return {
    mutationFn: (body: BoardCatalogBulkDecision) =>
      adminFetchJson<{ updated: number; status: string }>(boardCatalogCandidatesBulkPath(), {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => invalidateCatalog(qc),
  };
}

export function useBoardCatalogMutations() {
  const qc = useQueryClient();
  const preview = useMutation({
    mutationFn: (source: string) =>
      adminFetchJson<{ ok?: boolean; queued?: boolean; source?: string }>(boardCatalogBulkPreviewPath(source), {
        method: "POST",
        body: JSON.stringify({ remote: true }),
      }),
    onSuccess: () => invalidateCatalog(qc),
  });
  const importSource = useMutation({
    mutationFn: (source: string) =>
      adminFetchJson<{ ok?: boolean; queued?: boolean; source?: string }>(boardCatalogBulkImportPath(source), {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => invalidateCatalog(qc),
  });
  const decide = useMutation(catalogDecideMutationOptions(qc));
  const bulkDecide = useMutation(catalogBulkDecideMutationOptions(qc));
  const runDiscovery = useMutation({
    mutationFn: () =>
      adminFetchJson<{ ok?: boolean; queued?: boolean; skipped?: string }>(boardCatalogDiscoveryRunPath(), {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => invalidateCatalog(qc),
  });
  return { preview, importSource, decide, bulkDecide, runDiscovery };
}
