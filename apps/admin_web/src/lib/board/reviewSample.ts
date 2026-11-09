/** One row of the daily review "Sample of what ran": a hold-0 write call plus its task context. */

export type BoardReviewSampleTask = {
  readonly taskId: string;
  readonly assignee?: string;
  readonly status?: string;
  readonly brief?: string;
  readonly summary?: string;
};

export type BoardReviewSample = {
  readonly callId: string;
  readonly summary?: string;
  readonly preview?: unknown;
  readonly op?: string;
  readonly classKey?: string;
  readonly createdAt?: string;
  readonly personaId?: string;
  readonly displayName?: string;
  readonly seatId?: string;
  readonly taskId?: string;
  readonly arguments?: string;
  /** Pretty-printed JSON deliverable for a `task_finish` row. Empty when the body is not JSON. */
  readonly deliverablePreview?: string;
  readonly task?: BoardReviewSampleTask | null;
};
