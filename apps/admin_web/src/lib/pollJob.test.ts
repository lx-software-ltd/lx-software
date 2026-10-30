import { describe, expect, it, vi } from "vitest";
import { assertJobDone, pollJob, type PollableJob } from "./pollJob";

const wait = vi.fn(async () => undefined);

describe("pollJob", () => {
  it("loads until the job leaves the queue", async () => {
    const load = vi
      .fn<(_jobId: string) => Promise<PollableJob>>()
      .mockResolvedValueOnce({ jobId: "j1", status: "running", error: "" })
      .mockResolvedValueOnce({ jobId: "j1", status: "done", error: "" });
    const seen: string[] = [];
    const done = await pollJob({ jobId: "j1", status: "queued", error: "" }, load, wait, (job) => seen.push(job.status));
    expect(done.status).toBe("done");
    expect(seen).toEqual(["running", "done"]);
    expect(load).toHaveBeenCalledTimes(2);
    expect(wait).toHaveBeenCalledWith(1500);
  });

  it("rejects a failed or unfinished job", () => {
    expect(() => assertJobDone({ jobId: "j", status: "failed", error: "cap" })).toThrow("cap");
    expect(() => assertJobDone({ jobId: "j", status: "failed", error: "" })).toThrow("Generation failed.");
    expect(() => assertJobDone({ jobId: "j", status: "queued", error: "" })).toThrow(
      "Generation is still queued.",
    );
  });
});
