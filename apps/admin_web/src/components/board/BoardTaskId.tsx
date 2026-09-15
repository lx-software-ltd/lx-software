import { BoardCopyableId } from "./BoardCopyableId";

export function BoardTaskId({
  taskId,
  compact = false,
  full = false,
}: {
  readonly taskId: string;
  readonly compact?: boolean;
  readonly full?: boolean;
}) {
  return <BoardCopyableId id={taskId} noun="Task" compact={compact} full={full} />;
}
