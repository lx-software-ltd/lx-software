import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  boardTaskCancelPath,
  boardTaskPath,
  boardTaskReviewPath,
  boardTasksPath,
  tasksNeedPolling,
  type BoardTask,
  type BoardTaskCreate,
  type BoardTaskDetailPayload,
  type BoardTaskListPayload,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";
import { BOARD_STAFF_KEY } from "./useBoardStaff";

export const BOARD_TASKS_KEY = [...BOARD_QUERY_KEY, "tasks"] as const;

export function boardTaskDetailKey(taskId: string) {
  return [...BOARD_TASKS_KEY, "detail", taskId] as const;
}

function invalidateTasks(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: BOARD_TASKS_KEY });
  void qc.invalidateQueries({ queryKey: BOARD_STAFF_KEY });
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

export function useBoardTasks() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: BOARD_TASKS_KEY,
    queryFn: () => adminFetchJson<BoardTaskListPayload>(boardTasksPath()),
    refetchInterval: (q) => (tasksNeedPolling(q.state.data?.tasks ?? []) ? 10_000 : false),
  });
  const create = useMutation(createTaskMutationOptions(qc));
  const cancel = useMutation(cancelTaskMutationOptions(qc));
  const review = useMutation(reviewTaskMutationOptions(qc));
  return {
    tasks: query.data?.tasks ?? [],
    counts: query.data?.counts ?? {},
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    create,
    cancel,
    review,
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
