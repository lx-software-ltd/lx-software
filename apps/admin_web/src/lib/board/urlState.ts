import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { isRowExpandedParam } from "../expandedRecord";


export function readBoardTaskIdFromSearch(search: string): string | null {
  const raw = search.startsWith("?") ? search.slice(1) : search;
  const id = new URLSearchParams(raw).get("task")?.trim() ?? "";
  return id || null;
}


export function boardTaskSearchParams(
  taskId: string | null,
  currentSearch = "",
): URLSearchParams {
  const params = new URLSearchParams(currentSearch.startsWith("?") ? currentSearch.slice(1) : currentSearch);
  if (taskId) {
    params.set("tab", "board");
    params.set("section", "tasks");
    params.set("task", taskId);
  } else {
    params.delete("task");
  }
  return params;
}


export function boardTaskHref(taskId: string, currentSearch = ""): string {
  return `?${boardTaskSearchParams(taskId, currentSearch).toString()}`;
}

/** Writes the task query param through React Router so it stays aligned with useLocation. */
export function useBoardTaskParamWriter() {
  const [, setParams] = useSearchParams();
  return useCallback(
    (taskId: string | null) => {
      setParams(
        (prev) => {
          const next = boardTaskSearchParams(taskId, prev.toString());
          if (taskId) {
            for (const key of [...next.keys()]) {
              if (isRowExpandedParam(key)) next.delete(key);
            }
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );
}
