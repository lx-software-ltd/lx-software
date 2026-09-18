import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  boardCatalogBulkImportPath,
  boardCatalogBulkPreviewPath,
  boardCatalogCandidateDecidePath,
  boardCatalogCandidatesPath,
  boardCatalogDiscoveryRunPath,
  boardCatalogSourcesPath,
  type BoardCatalogCandidate,
  type BoardCatalogSourcesPayload,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";
import { BOARD_PROGRESS_KEY } from "./useBoardProgress";

export const BOARD_CATALOG_SOURCES_KEY = [...BOARD_QUERY_KEY, "catalog-sources"] as const;
export const BOARD_CATALOG_CANDIDATES_KEY = [...BOARD_QUERY_KEY, "catalog-candidates"] as const;

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

export function useBoardCatalogCandidates(status?: string) {
  return useQuery({
    queryKey: [...BOARD_CATALOG_CANDIDATES_KEY, status || "all"],
    queryFn: () =>
      adminFetchJson<{ candidates: BoardCatalogCandidate[] }>(boardCatalogCandidatesPath(status)).then(
        (res) => res.candidates,
      ),
  });
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
  const decide = useMutation({
    mutationFn: ({ candidateId, decision }: { candidateId: string; decision: "approve" | "reject" }) =>
      adminFetchJson<{ candidate: BoardCatalogCandidate }>(boardCatalogCandidateDecidePath(candidateId, decision), {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => invalidateCatalog(qc),
  });
  const runDiscovery = useMutation({
    mutationFn: () =>
      adminFetchJson<{ ok?: boolean; queued?: boolean; skipped?: string }>(boardCatalogDiscoveryRunPath(), {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => invalidateCatalog(qc),
  });
  return { preview, importSource, decide, runDiscovery };
}
