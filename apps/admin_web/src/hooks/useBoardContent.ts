import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  boardContentItemPath,
  boardContentPath,
  boardContentRenderPath,
  type BoardContentItem,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";

export const BOARD_CONTENT_KEY = [...BOARD_QUERY_KEY, "content"] as const;

export function contentPutMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ contentId, body }: { readonly contentId: string; readonly body: Record<string, unknown> }) => {
      const res = await adminFetchJson<{ item: BoardContentItem }>(boardContentItemPath(contentId), {
        method: "PUT",
        body: JSON.stringify(body),
      });
      return res.item;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_CONTENT_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
    },
  };
}

export function useBoardContent() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: BOARD_CONTENT_KEY,
    queryFn: () => adminFetchJson<{ items: BoardContentItem[]; assisted: BoardContentItem[] }>(boardContentPath()),
  });
  const create = useMutation({
    mutationFn: async (body: Record<string, unknown>) => {
      const res = await adminFetchJson<{ item: BoardContentItem }>(boardContentPath(), {
        method: "POST",
        body: JSON.stringify(body),
      });
      return res.item;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_CONTENT_KEY });
    },
  });
  const update = useMutation(contentPutMutationOptions(qc));
  const render = useMutation({
    mutationFn: async (contentId: string) => {
      const res = await adminFetchJson<{ item: BoardContentItem }>(boardContentRenderPath(contentId), { method: "POST" });
      return res.item;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_CONTENT_KEY });
    },
  });
  return {
    items: list.data?.items ?? [],
    assisted: list.data?.assisted ?? [],
    isLoading: list.isLoading,
    error: list.error,
    create,
    update,
    render,
  };
}
