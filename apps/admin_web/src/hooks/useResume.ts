import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import { assertJobDone, pollJob } from "../lib/pollJob";
import type {
  JobApplication,
  JobPosting,
  ResumeDetail,
  ResumeFileBody,
  ResumeJob,
  ResumeOverview,
  ResumeSettings,
  ResumeSummary,
} from "../lib/resumeModel";

export const RESUME_KEY = ["resume"] as const;

async function loadJob(jobId: string): Promise<ResumeJob> {
  const next = await adminFetchJson<{ job: ResumeJob }>(`/lx-software/resume/jobs/${jobId}`);
  return next.job;
}

export function useResume() {
  const qc = useQueryClient();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: RESUME_KEY });
  };
  const overview = useQuery({
    queryKey: [...RESUME_KEY, "overview"] as const,
    queryFn: () => adminFetchJson<ResumeOverview>("/lx-software/resume/overview"),
  });
  const resumes = useQuery({
    queryKey: [...RESUME_KEY, "resumes"] as const,
    queryFn: () => adminFetchJson<{ items: ResumeSummary[] }>("/lx-software/resume/resumes"),
  });
  const postings = useQuery({
    queryKey: [...RESUME_KEY, "postings"] as const,
    queryFn: () => adminFetchJson<{ items: JobPosting[] }>("/lx-software/resume/postings"),
  });
  const applications = useQuery({
    queryKey: [...RESUME_KEY, "applications"] as const,
    queryFn: () => adminFetchJson<{ items: JobApplication[] }>("/lx-software/resume/applications"),
  });
  const saveSettings = useMutation({
    mutationFn: (body: ResumeSettings) =>
      adminFetchJson<{ settings: ResumeSettings }>("/lx-software/resume/settings", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: refresh,
  });
  const upload = useMutation({
    mutationFn: async (body: {
      title: string;
      contentType: string;
      dataBase64: string;
      makeTemplate: boolean;
      onStatus?: (status: string) => void;
    }) => {
      const { onStatus, ...payload } = body;
      const queued = await adminFetchJson<{ resume: ResumeSummary; job: ResumeJob }>("/lx-software/resume/resumes", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const job = assertJobDone(
        await pollJob(queued.job, loadJob, undefined, (next) => onStatus?.(next.status)),
      );
      return { resume: queued.resume, job };
    },
    onSettled: refresh,
  });
  const setTemplate = useMutation({
    mutationFn: (resumeId: string) =>
      adminFetchJson("/lx-software/resume/template", {
        method: "PUT",
        body: JSON.stringify({ resumeId }),
      }),
    onSuccess: refresh,
  });
  const patchResume = useMutation({
    mutationFn: (body: { id: string; title?: string; overrides?: Record<string, string> }) =>
      adminFetchJson<{ item: ResumeDetail }>(`/lx-software/resume/resumes/${body.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title: body.title, overrides: body.overrides }),
      }),
    onSuccess: refresh,
  });
  const deleteResume = useMutation({
    mutationFn: (id: string) => adminFetchJson(`/lx-software/resume/resumes/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const tailor = useMutation({
    mutationFn: async (body: {
      templateId?: string;
      postingId?: string;
      posting?: { title: string; company: string; adText: string };
      addToTracker: boolean;
      onStatus?: (status: string) => void;
    }) => {
      const { onStatus, ...payload } = body;
      const queued = await adminFetchJson<{ job: ResumeJob }>("/lx-software/resume/tailor", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      return assertJobDone(await pollJob(queued.job, loadJob, undefined, (next) => onStatus?.(next.status)));
    },
    onSettled: refresh,
  });
  const saveApplication = useMutation({
    mutationFn: (body: Partial<JobApplication> & { id?: string }) => {
      if (body.id) {
        return adminFetchJson<{ item: JobApplication }>(`/lx-software/resume/applications/${body.id}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
      }
      return adminFetchJson<{ item: JobApplication }>("/lx-software/resume/applications", {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    onSuccess: refresh,
  });
  const deleteApplication = useMutation({
    mutationFn: (id: string) => adminFetchJson(`/lx-software/resume/applications/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  return {
    overview,
    resumes,
    postings,
    applications,
    saveSettings,
    upload,
    setTemplate,
    patchResume,
    deleteResume,
    tailor,
    saveApplication,
    deleteApplication,
  };
}

export function useResumeDetail(id: string | null) {
  return useQuery({
    queryKey: [...RESUME_KEY, "resume", id] as const,
    enabled: Boolean(id && id !== "new"),
    queryFn: () => adminFetchJson<{ item: ResumeDetail }>(`/lx-software/resume/resumes/${id}`),
  });
}

export async function fetchResumeFile(id: string, kind: "file" | "pdf"): Promise<ResumeFileBody> {
  return adminFetchJson<ResumeFileBody>(`/lx-software/resume/resumes/${id}/${kind}`);
}
