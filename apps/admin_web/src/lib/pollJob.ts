export const POLL_ATTEMPTS = 200;
export const POLL_MS = 1500;

export type PollableJob = {
  jobId: string;
  status: string;
  error: string;
};

export async function pollJob<T extends PollableJob>(
  job: T,
  load: (jobId: string) => Promise<T>,
  wait: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  onUpdate?: (job: T) => void,
): Promise<T> {
  let current = job;
  for (
    let attempt = 0;
    attempt < POLL_ATTEMPTS && (current.status === "queued" || current.status === "running");
    attempt += 1
  ) {
    await wait(POLL_MS);
    current = await load(current.jobId);
    onUpdate?.(current);
  }
  return current;
}

export function assertJobDone<T extends PollableJob>(job: T): T {
  if (job.status === "failed") throw new Error(job.error || "Generation failed.");
  if (job.status !== "done") throw new Error("Generation is still queued.");
  if (job.error) throw new Error(job.error);
  return job;
}
