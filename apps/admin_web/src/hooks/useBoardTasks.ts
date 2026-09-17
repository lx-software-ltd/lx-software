import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  boardCatalogImportPath,
  boardCatalogPreviewPath,
  boardCatalogRequeuePath,
  boardCatalogSkipPath,
  boardTaskCancelPath,
  boardTaskPath,
  boardTaskReviewPath,
  boardTaskRetryPath,
  boardTasksPath,
  tasksNeedPolling,
  type BoardCatalogImportPreview,
  type BoardTask,
  type BoardTaskCreate,
  type BoardTaskDetailPayload,
  type BoardTaskListPayload,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";
import { BOARD_ACTIONS_KEY } from "./useBoardActions";
import { BOARD_STAFF_KEY } from "./useBoardStaff";

export const BOARD_TASKS_KEY = [...BOARD_QUERY_KEY, "tasks"] as const;

export function boardTaskDetailKey(taskId: string) {
  return [...BOARD_TASKS_KEY, "detail", taskId] as const;
}

function invalidateTasks(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: BOARD_TASKS_KEY });
  void qc.invalidateQueries({ queryKey: BOARD_STAFF_KEY });
  // Tasks linked to a founder action change its assignee / status.
  void qc.invalidateQueries({ queryKey: BOARD_ACTIONS_KEY });
}

export function createTaskMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (body: BoardTaskCreate) => {
      const res = await adminFetchJson<{ task: BoardTask }>(boardTasksPath(), {
        method: "POST",
        body: JSON.stringify(body),
      });
      return res.task;
    },
    onSuccess: () => invalidateTasks(qc),
  };
}

export function cancelTaskMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (taskId: string) => {
      const res = await adminFetchJson<{ task: BoardTask }>(boardTaskCancelPath(taskId), {
        method: "POST",
        body: JSON.stringify({}),
      });
      return res.task;
    },
    onSuccess: () => invalidateTasks(qc),
  };
}

export function retryTaskMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (taskId: string) => {
      const res = await adminFetchJson<{ task: BoardTask }>(boardTaskRetryPath(taskId), {
        method: "POST",
        body: JSON.stringify({}),
      });
      return res.task;
    },
    onSuccess: () => invalidateTasks(qc),
  };
}

export function catalogPreviewMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (taskId: string) => {
      const res = await adminFetchJson<{ preview: BoardCatalogImportPreview }>(boardCatalogPreviewPath(), {
        method: "POST",
        body: JSON.stringify({ taskId }),
      });
      return res.preview;
    },
    onSuccess: (_preview: BoardCatalogImportPreview, taskId: string) => {
      void qc.invalidateQueries({ queryKey: boardTaskDetailKey(taskId) });
      void qc.invalidateQueries({ queryKey: BOARD_TASKS_KEY });
    },
  };
}

export function catalogImportMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ taskId, force }: { taskId: string; force?: boolean }) => {
      const res = await adminFetchJson<{ ok: boolean; preview?: BoardCatalogImportPreview; taskId?: string }>(
        boardCatalogImportPath(),
        {
          method: "POST",
          body: JSON.stringify({ taskId, force: Boolean(force) }),
        },
      );
      return res;
    },
    onSuccess: () => invalidateTasks(qc),
  };
}

export function catalogSkipMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (taskId: string) => {
      const res = await adminFetchJson<{ ok: boolean; task?: BoardTask }>(boardCatalogSkipPath(), {
        method: "POST",
        body: JSON.stringify({ taskId }),
      });
      return res;
    },
    onSuccess: () => invalidateTasks(qc),
  };
}

export function catalogRequeueMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (taskId: string) => {
      const res = await adminFetchJson<{ ok: boolean; task?: BoardTask }>(boardCatalogRequeuePath(), {
        method: "POST",
        body: JSON.stringify({ taskId }),
      });
      return res;
    },
    onSuccess: () => invalidateTasks(qc),
  };
}

export function reviewTaskMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({
      taskId,
      verdict,
      notes,
    }: {
      taskId: string;
      verdict: "accept" | "return";
      notes: string;
    }) => {
      const res = await adminFetchJson<{ task: BoardTask }>(boardTaskReviewPath(taskId), {
        method: "POST",
        body: JSON.stringify({ verdict, notes }),
      });
      return res.task;
    },
    onSuccess: () => invalidateTasks(qc),
  };
}

async function fetchTaskList(): Promise<BoardTaskListPayload> {
  const [main, failed] = await Promise.all([
    adminFetchJson<BoardTaskListPayload>(boardTasksPath()),
    adminFetchJson<BoardTaskListPayload>(boardTasksPath({ status: "failed", limit: 50 })),
  ]);
  const seen = new Set(main.tasks.map((task) => task.taskId));
  const extra = failed.tasks.filter((task) => !seen.has(task.taskId));
  return {
    tasks: extra.length ? [...main.tasks, ...extra] : main.tasks,
    counts: main.counts,
  };
}

export function useBoardTasks() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: BOARD_TASKS_KEY,
    queryFn: fetchTaskList,
    refetchInterval: (q) => (tasksNeedPolling(q.state.data?.tasks ?? []) ? 10_000 : false),
  });
  const create = useMutation(createTaskMutationOptions(qc));
  const cancel = useMutation(cancelTaskMutationOptions(qc));
  const review = useMutation(reviewTaskMutationOptions(qc));
  const retry = useMutation(retryTaskMutationOptions(qc));
  const catalogPreview = useMutation(catalogPreviewMutationOptions(qc));
  const catalogImport = useMutation(catalogImportMutationOptions(qc));
  const catalogSkip = useMutation(catalogSkipMutationOptions(qc));
  const catalogRequeue = useMutation(catalogRequeueMutationOptions(qc));
  return {
    tasks: query.data?.tasks ?? [],
    counts: query.data?.counts ?? {},
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    dataUpdatedAt: query.dataUpdatedAt,
    isError: query.isError,
    error: query.error,
    create,
    cancel,
    review,
    retry,
    catalogPreview,
    catalogImport,
    catalogSkip,
    catalogRequeue,
  };
}

export function useBoardTask(taskId: string | null) {
  return useQuery({
    queryKey: taskId ? boardTaskDetailKey(taskId) : [...BOARD_TASKS_KEY, "detail", "none"],
    queryFn: () => adminFetchJson<BoardTaskDetailPayload>(boardTaskPath(taskId ?? "")),
    enabled: Boolean(taskId),
    refetchInterval: (q) => {
      const status = q.state.data?.task.status;
      return status === "running" || status === "review" ? 10_000 : false;
    },
  });
}
