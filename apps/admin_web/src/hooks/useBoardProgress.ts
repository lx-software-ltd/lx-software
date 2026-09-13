import { useQuery } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import { boardProgressPath, type BoardProgressSnapshot } from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";

export const BOARD_PROGRESS_KEY = [...BOARD_QUERY_KEY, "progress"] as const;

export function useBoardProgress() {
  return useQuery({
    queryKey: BOARD_PROGRESS_KEY,
    queryFn: () => adminFetchJson<BoardProgressSnapshot>(boardProgressPath()),
    refetchInterval: 30_000,
  });
}
