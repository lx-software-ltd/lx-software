import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import type { LinkedInIdea, LinkedInOverview, LinkedInPost, LinkedInSettings } from "../lib/linkedinModel";

export const LINKEDIN_KEY = ["linkedin"] as const;

type Job = { jobId: string; status: string; postIds: string[]; error: string };

async function pollJob(job: Job): Promise<Job> {
  let current = job;
  for (let attempt = 0; attempt < 40 && (current.status === "queued" || current.status === "running"); attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    const next = await adminFetchJson<{ job: Job }>(`/lx-software/linkedin/jobs/${current.jobId}`);
    current = next.job;
  }
  return current;
}

export function useLinkedIn() {
  const qc = useQueryClient();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: LINKEDIN_KEY });
  };
  const overview = useQuery({
    queryKey: [...LINKEDIN_KEY, "overview"] as const,
    queryFn: () => adminFetchJson<LinkedInOverview>("/lx-software/linkedin"),
  });
  const posts = useQuery({
    queryKey: [...LINKEDIN_KEY, "posts"] as const,
    queryFn: () => adminFetchJson<{ items: LinkedInPost[] }>("/lx-software/linkedin/posts"),
  });
  const ideas = useQuery({
    queryKey: [...LINKEDIN_KEY, "ideas"] as const,
    queryFn: () => adminFetchJson<{ items: LinkedInIdea[] }>("/lx-software/linkedin/ideas"),
  });
  const saveSettings = useMutation({
    mutationFn: (body: LinkedInSettings) =>
      adminFetchJson<{ settings: LinkedInSettings }>("/lx-software/linkedin/settings", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: refresh,
  });
  const createPost = useMutation({
    mutationFn: (body: Partial<LinkedInPost>) =>
      adminFetchJson<{ item: LinkedInPost }>("/lx-software/linkedin/posts", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: refresh,
  });
  const updatePost = useMutation({
    mutationFn: ({ postId, body }: { postId: string; body: Partial<LinkedInPost> }) =>
      adminFetchJson<{ item: LinkedInPost }>(`/lx-software/linkedin/posts/${postId}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: refresh,
  });
  const act = useMutation({
    mutationFn: ({ postId, action, body }: { postId: string; action: string; body?: Record<string, unknown> }) =>
      adminFetchJson<{ item: LinkedInPost }>(`/lx-software/linkedin/posts/${postId}/${action}`, {
        method: "POST",
        body: JSON.stringify(body ?? {}),
      }),
    onSuccess: refresh,
  });
  const createIdea = useMutation({
    mutationFn: (body: { text: string; pillar: string }) =>
      adminFetchJson<{ item: LinkedInIdea }>("/lx-software/linkedin/ideas", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: refresh,
  });
  const deleteIdea = useMutation({
    mutationFn: (ideaId: string) =>
      adminFetchJson(`/lx-software/linkedin/ideas/${ideaId}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const regenerate = useMutation({
    mutationFn: async (postId: string) => {
      const queued = await adminFetchJson<{ job: Job }>(`/lx-software/linkedin/posts/${postId}/regenerate`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      const job = await pollJob(queued.job);
      if (job.status === "failed") throw new Error(job.error || "Generation failed.");
      if (job.status !== "done") throw new Error("Generation is still queued.");
      return job;
    },
    onSuccess: refresh,
  });
  const generate = useMutation({
    mutationFn: async (body: { count?: number; pillar?: string }) => {
      const queued = await adminFetchJson<{ job: Job }>("/lx-software/linkedin/generate", {
        method: "POST",
        body: JSON.stringify(body),
      });
      const job = await pollJob(queued.job);
      if (job.status === "failed") throw new Error(job.error || "Generation failed.");
      if (job.status !== "done") throw new Error("Generation is still queued.");
      return job;
    },
    onSuccess: refresh,
  });
  return {
    overview,
    posts,
    ideas,
    saveSettings,
    createPost,
    updatePost,
    act,
    createIdea,
    deleteIdea,
    generate,
    regenerate,
  };
}
