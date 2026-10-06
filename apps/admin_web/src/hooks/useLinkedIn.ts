import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import type {
  LinkedInCharacter,
  LinkedInConnection,
  LinkedInDraftSettings,
  LinkedInIdea,
  LinkedInOverview,
  LinkedInPost,
} from "../lib/linkedinModel";

export const LINKEDIN_KEY = ["linkedin"] as const;
/** Picture bytes. Kept off `LINKEDIN_KEY` so a draft save does not refetch them. */
export const LINKEDIN_BYTES_KEY = ["linkedin-bytes"] as const;

type Job = { jobId: string; status: string; postIds: string[]; error: string };

const POLL_ATTEMPTS = 200;
const POLL_MS = 1500;

async function pollJob(job: Job): Promise<Job> {
  let current = job;
  for (let attempt = 0; attempt < POLL_ATTEMPTS && (current.status === "queued" || current.status === "running"); attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    const next = await adminFetchJson<{ job: Job }>(`/lx-software/linkedin/jobs/${current.jobId}`);
    current = next.job;
  }
  return current;
}

function assertJobDone(job: Job): Job {
  if (job.status === "failed") throw new Error(job.error || "Generation failed.");
  if (job.status !== "done") throw new Error("Generation is still queued.");
  if (job.error) throw new Error(job.error);
  return job;
}

function pendingPollDelay(pendingSince: number): number {
  const age = Date.now() - pendingSince;
  if (age < 20_000) return 3_000;
  if (age < 60_000) return 8_000;
  return 15_000;
}

export function useLinkedIn() {
  const qc = useQueryClient();
  const pendingSince = useRef<number | null>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: LINKEDIN_KEY });
  };
  const refreshCharacterBytes = () => {
    void qc.invalidateQueries({ queryKey: [...LINKEDIN_BYTES_KEY, "character"] });
  };
  const refreshPostBytes = (postId: string) => {
    void qc.invalidateQueries({ queryKey: [...LINKEDIN_BYTES_KEY, "post", postId] });
  };
  const overview = useQuery({
    queryKey: [...LINKEDIN_KEY, "overview"] as const,
    queryFn: () => adminFetchJson<LinkedInOverview>("/lx-software/linkedin"),
  });
  const posts = useQuery({
    queryKey: [...LINKEDIN_KEY, "posts"] as const,
    queryFn: () => adminFetchJson<{ items: LinkedInPost[] }>("/lx-software/linkedin/posts"),
    refetchInterval: (query) => {
      const pending = query.state.data?.items.some((row) => row.image?.status === "pending") ?? false;
      if (!pending) {
        pendingSince.current = null;
        return false;
      }
      if (pendingSince.current === null) pendingSince.current = Date.now();
      return pendingPollDelay(pendingSince.current);
    },
  });
  const ideas = useQuery({
    queryKey: [...LINKEDIN_KEY, "ideas"] as const,
    queryFn: () => adminFetchJson<{ items: LinkedInIdea[] }>("/lx-software/linkedin/ideas"),
  });
  const character = useQuery({
    queryKey: [...LINKEDIN_KEY, "character"] as const,
    queryFn: () => adminFetchJson<LinkedInCharacter>("/lx-software/linkedin/character"),
  });
  const saveSettings = useMutation({
    mutationFn: (body: LinkedInDraftSettings) =>
      adminFetchJson<{ settings: LinkedInDraftSettings }>("/lx-software/linkedin/settings", {
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
      return assertJobDone(await pollJob(queued.job));
    },
    onSettled: refresh,
  });
  const connect = useMutation({
    mutationFn: (includeOrganizations: boolean) =>
      adminFetchJson<{ url: string }>("/lx-software/linkedin/connect", {
        method: "POST",
        body: JSON.stringify({ includeOrganizations }),
      }),
  });
  const completeAuth = useMutation({
    mutationFn: (body: { code: string; state: string }) =>
      adminFetchJson<{ connection: LinkedInConnection }>("/lx-software/linkedin/oauth/exchange", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: refresh,
  });
  const disconnect = useMutation({
    mutationFn: () => adminFetchJson("/lx-software/linkedin/disconnect", { method: "POST", body: "{}" }),
    onSuccess: refresh,
  });
  const refreshOrganizations = useMutation({
    mutationFn: () =>
      adminFetchJson<{ connection: LinkedInConnection }>("/lx-software/linkedin/connection/refresh", {
        method: "POST",
        body: "{}",
      }),
    onSuccess: refresh,
  });
  const saveConnection = useMutation({
    mutationFn: (body: { channel: string; organizationId: string }) =>
      adminFetchJson<{ connection: LinkedInConnection }>("/lx-software/linkedin/connection", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: refresh,
  });
  const uploadImage = useMutation({
    mutationFn: ({ postId, contentType, dataBase64 }: { postId: string; contentType: string; dataBase64: string }) =>
      adminFetchJson<{ item: LinkedInPost }>(`/lx-software/linkedin/posts/${postId}/image`, {
        method: "POST",
        body: JSON.stringify({ contentType, dataBase64 }),
      }),
    onSuccess: (_data, { postId }) => {
      refresh();
      refreshPostBytes(postId);
    },
  });
  const deleteImage = useMutation({
    mutationFn: (postId: string) =>
      adminFetchJson<{ item: LinkedInPost }>(`/lx-software/linkedin/posts/${postId}/image`, { method: "DELETE" }),
    onSuccess: (_data, postId) => {
      refresh();
      refreshPostBytes(postId);
    },
  });
  const redrawImage = useMutation({
    mutationFn: ({
      postId,
      scene,
      caption,
      expression,
    }: {
      postId: string;
      scene: string;
      caption: string;
      expression: string;
    }) =>
      adminFetchJson<{ item: LinkedInPost }>(`/lx-software/linkedin/posts/${postId}/image/regenerate`, {
        method: "POST",
        body: JSON.stringify({ scene, caption, expression }),
      }),
    onSuccess: (_data, { postId }) => {
      refresh();
      refreshPostBytes(postId);
    },
  });
  const rewriteBrief = useMutation({
    mutationFn: (postId: string) =>
      adminFetchJson<{ item: LinkedInPost }>(`/lx-software/linkedin/posts/${postId}/image/brief`, {
        method: "POST",
        body: "{}",
      }),
    onSuccess: refresh,
  });
  const uploadCharacterPhoto = useMutation({
    mutationFn: ({ contentType, dataBase64 }: { contentType: string; dataBase64: string }) =>
      adminFetchJson<LinkedInCharacter>("/lx-software/linkedin/character/photo", {
        method: "POST",
        body: JSON.stringify({ contentType, dataBase64 }),
      }),
    onSuccess: () => {
      refresh();
      refreshCharacterBytes();
    },
  });
  const deleteCharacterPhoto = useMutation({
    mutationFn: () => adminFetchJson<LinkedInCharacter>("/lx-software/linkedin/character/photo", { method: "DELETE" }),
    onSuccess: () => {
      refresh();
      refreshCharacterBytes();
    },
  });
  const drawCharacter = useMutation({
    mutationFn: async () => {
      const queued = await adminFetchJson<{ job: Job }>("/lx-software/linkedin/character/draw", {
        method: "POST",
        body: "{}",
      });
      return assertJobDone(await pollJob(queued.job));
    },
    onSettled: () => {
      refresh();
      refreshCharacterBytes();
    },
  });
  const chooseCharacter = useMutation({
    mutationFn: (candidateId: string) =>
      adminFetchJson<LinkedInCharacter>("/lx-software/linkedin/character/choose", {
        method: "POST",
        body: JSON.stringify({ candidateId }),
      }),
    onSuccess: () => {
      refresh();
      refreshCharacterBytes();
    },
  });
  const generate = useMutation({
    mutationFn: async (body: { count?: number; pillar?: string }) => {
      const queued = await adminFetchJson<{ job: Job }>("/lx-software/linkedin/generate", {
        method: "POST",
        body: JSON.stringify(body),
      });
      return assertJobDone(await pollJob(queued.job));
    },
    onSettled: refresh,
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
    connect,
    completeAuth,
    disconnect,
    saveConnection,
    refreshOrganizations,
    uploadImage,
    deleteImage,
    redrawImage,
    rewriteBrief,
    character,
    uploadCharacterPhoto,
    deleteCharacterPhoto,
    drawCharacter,
    chooseCharacter,
  };
}
