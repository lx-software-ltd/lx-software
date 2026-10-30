import {
  DOCX_TYPE,
  MD_TYPE,
  PDF_TYPE,
  TEXT_TYPE,
  type JobApplication,
  type JobPosting,
  type ResumeJob,
  type ResumeSummary,
} from "../../resumeModel";
import sampleDocx from "../sample-resume.docx.b64?raw";
import samplePdf from "../sample-resume.pdf.b64?raw";
import { json, parseBody, state, type ResumeMockJob, type StoredResume } from "./context";
import type { MockCtx } from "./types";

const DOCX_B64 = sampleDocx.trim();
const PDF_B64 = samplePdf.trim();
const FORMATS: Record<string, "docx" | "pdf" | "md"> = {
  [DOCX_TYPE]: "docx",
  [PDF_TYPE]: "pdf",
  [MD_TYPE]: "md",
  [TEXT_TYPE]: "md",
};

function nowIso(): string {
  return new Date().toISOString();
}

function nextId(prefix: string): string {
  state.resume.seq += 1;
  return `${prefix}_${state.resume.seq}`;
}

function publicJob(job: ResumeMockJob): ResumeJob {
  return {
    jobId: job.jobId,
    status: job.status,
    resumeIds: [...job.resumeIds],
    error: job.error,
    findings: [...job.findings],
  };
}

function publicResume(row: StoredResume, detail: boolean): ResumeSummary | StoredResume {
  const item: ResumeSummary = {
    id: row.id,
    title: row.title,
    kind: row.kind,
    format: row.format,
    source: row.source,
    file: { contentType: row.file.contentType, size: row.file.size },
    extract: { status: row.extract.status, error: row.extract.error },
    derivedFrom: row.derivedFrom,
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
  };
  if (!detail) return item;
  return { ...row, ...item, makeTemplate: undefined, dataBase64: undefined };
}

function settleJobs(): void {
  const now = Date.now();
  for (const job of state.resume.jobs) {
    if (job.settled) continue;
    if (now < job.doneAt) {
      if (now >= job.runningAt && job.status === "queued") job.status = "running";
      continue;
    }
    job.finish();
    job.settled = true;
    if (job.status !== "failed") job.status = "done";
  }
}

function queueJob(finish: (job: ResumeMockJob) => void): ResumeMockJob {
  const stamp = Date.now();
  const job: ResumeMockJob = {
    jobId: nextId("job"),
    status: "queued",
    resumeIds: [],
    error: "",
    findings: [],
    runningAt: stamp + 1000,
    doneAt: stamp + 1000,
    settled: false,
    finish: () => undefined,
  };
  job.finish = () => finish(job);
  state.resume.jobs.push(job);
  return job;
}

function paragraphsFor(title: string): StoredResume["paragraphs"] {
  return [
    { id: "p0", text: title, style: "Title", numbered: false, inTable: false, inTextBox: false, runs: 1, chars: title.length },
    { id: "p1", text: "Engineer", style: "Heading1", numbered: false, inTable: false, inTextBox: false, runs: 1, chars: 8 },
    { id: "p2", text: "Builds billing exports.", style: "Normal", numbered: false, inTable: false, inTextBox: false, runs: 1, chars: 23 },
    { id: "p3", text: "Shipped the monthly export.", style: "ListBullet", numbered: true, inTable: false, inTextBox: false, runs: 1, chars: 27 },
  ];
}

function layoutFor(paragraphs: StoredResume["paragraphs"]): StoredResume["layout"] {
  return {
    paragraphs: paragraphs.map((row, index) => ({
      id: row.id,
      role: index === 0 ? "name" : index === 1 ? "headline" : index === 2 ? "summary" : "bullet",
    })),
    roles: [{ headerId: "p1", bulletIds: ["p3"] }],
    overrides: {},
  };
}

function disabled(): Response | null {
  if (state.resume.enabled) return null;
  return json({ message: "Resume is turned off.", reason: "resume_disabled" }, 403);
}

function findResume(id: string): StoredResume | undefined {
  return state.resume.resumes.find((row) => row.id === id);
}

function recruiterOf(value: unknown, current: JobApplication["recruiter"]): JobApplication["recruiter"] | Response {
  const source = value && typeof value === "object" ? (value as Record<string, unknown>) : current;
  const email = String(source.email ?? "").trim();
  if (email && !email.includes("@")) return json({ message: "Recruiter email must contain @." }, 400);
  return {
    name: String(source.name ?? "").trim(),
    email,
    phone: String(source.phone ?? "").trim(),
  };
}

function calendarDay(value: unknown, label: string): string | Response {
  const text = String(value ?? "").trim();
  if (!text) return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!match) return json({ message: `${label} must be a YYYY-MM-DD date.` }, 400);
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) {
    return json({ message: `${label} must be a YYYY-MM-DD date.` }, 400);
  }
  return text;
}

function addPosting(raw: Record<string, unknown>): JobPosting | Response {
  const title = String(raw.title ?? "").trim();
  const company = String(raw.company ?? "").trim();
  const adText = String(raw.adText ?? "").trim();
  if (!title || !company || !adText) return json({ message: "Title, company, and the job post are required." }, 400);
  const posting: JobPosting = {
    id: nextId("post"),
    title,
    company,
    url: String(raw.url ?? ""),
    location: String(raw.location ?? ""),
    adText,
    createdAt: nowIso(),
  };
  state.resume.postings = [posting, ...state.resume.postings];
  return posting;
}

function fileBody(row: StoredResume, kind: "file" | "pdf"): Response {
  const pdf = kind === "pdf" || row.format === "pdf";
  const dataBase64 = pdf ? (row.format === "pdf" && row.dataBase64 ? row.dataBase64 : PDF_B64) : row.dataBase64 || DOCX_B64;
  const ext = pdf ? "pdf" : row.format === "docx" ? "docx" : "md";
  const filename = `${row.title.replace(/[^\w-]+/g, "-").replace(/^-|-$/g, "") || "resume"}.${ext}`;
  return json({
    contentType: pdf ? PDF_TYPE : row.file.contentType,
    filename,
    dataBase64,
  });
}

export function handleResume(ctx: MockCtx): Response | null {
  const { method, path } = ctx;
  if (path !== "/lx-software/resume" && !path.startsWith("/lx-software/resume/")) return null;
  settleJobs();
  const parts = path.slice("/lx-software/resume".length).split("/").filter(Boolean);
  const body = parseBody(ctx.init);
  const resumeState = state.resume;

  if (parts[0] === "overview" && method === "GET") {
    return json({
      enabled: resumeState.enabled,
      settings: resumeState.settings,
      templateResumeId: resumeState.templateResumeId,
      defaultModel: resumeState.defaultModel,
      spendUsdMonth: resumeState.spendUsdMonth,
      counts: {
        resumes: resumeState.resumes.length,
        postings: resumeState.postings.length,
        applications: resumeState.applications.length,
      },
      pdfCjk: resumeState.pdfCjk,
    });
  }
  if (parts[0] === "settings" && method === "GET") return json({ settings: resumeState.settings });
  if (parts[0] === "settings" && method === "PUT") {
    const blocked = disabled();
    if (blocked) return blocked;
    const page = String(body.pageSize ?? resumeState.settings.pageSize);
    if (page !== "A4" && page !== "Letter") return json({ message: "Page size must be A4 or Letter." }, 400);
    if (Array.isArray(body.rewriteScope) && body.rewriteScope.length === 0) {
      return json({ message: "Choose at least one part of the resume to rewrite." }, 400);
    }
    resumeState.settings = { ...resumeState.settings, ...body, pageSize: page } as typeof resumeState.settings;
    return json({ settings: resumeState.settings });
  }
  if (parts[0] === "resumes" && parts.length === 1 && method === "GET") {
    return json({ items: resumeState.resumes.map((row) => publicResume(row, false)) });
  }
  if (parts[0] === "resumes" && parts.length === 1 && method === "POST") {
    const blocked = disabled();
    if (blocked) return blocked;
    const title = String(body.title ?? "").trim();
    const contentType = String(body.contentType ?? "");
    const dataBase64 = String(body.dataBase64 ?? "");
    const format = FORMATS[contentType];
    if (!title) return json({ message: "Title is required and must be under 200 characters." }, 400);
    if (!dataBase64) return json({ message: "The file is empty." }, 400);
    if (!format) return json({ message: "Upload a Word document, PDF, Markdown, or text file." }, 400);
    if (body.makeTemplate && format !== "docx") {
      return json({ message: "Only a Word document can be the template." }, 400);
    }
    const id = nextId("res");
    const created: StoredResume = {
      id,
      title,
      kind: "archive",
      format,
      source: "upload",
      file: { contentType, size: Math.floor((dataBase64.length * 3) / 4) },
      extract: { status: "pending", error: "" },
      derivedFrom: null,
      createdAt: nowIso(),
      updatedAt: nowIso(),
      paragraphs: [],
      layout: { paragraphs: [], roles: [], overrides: {} },
      generation: null,
      makeTemplate: Boolean(body.makeTemplate),
      dataBase64,
    };
    resumeState.resumes = [created, ...resumeState.resumes];
    const job = queueJob((current) => {
      const row = findResume(id);
      if (!row) {
        current.status = "failed";
        current.error = "Resume not found";
        return;
      }
      const paragraphs = paragraphsFor(row.title);
      row.extract = { status: "ready", error: "" };
      row.paragraphs = paragraphs;
      row.layout = layoutFor(paragraphs);
      row.updatedAt = nowIso();
      if (row.makeTemplate && row.format === "docx") {
        for (const other of resumeState.resumes) {
          if (other.id !== row.id && other.kind === "template") other.kind = "archive";
        }
        row.kind = "template";
        resumeState.templateResumeId = row.id;
      }
      current.resumeIds = [row.id];
    });
    return json({ resume: publicResume(created, false), job: publicJob(job) }, 202);
  }
  if (parts[0] === "resumes" && parts.length === 2 && method === "GET") {
    const row = findResume(parts[1]);
    if (!row) return json({ message: "Resume not found" }, 404);
    return json({ item: publicResume(row, true) });
  }
  if (parts[0] === "resumes" && parts.length === 2 && method === "PATCH") {
    const blocked = disabled();
    if (blocked) return blocked;
    const row = findResume(parts[1]);
    if (!row) return json({ message: "Resume not found" }, 404);
    if (typeof body.title === "string" && body.title.trim()) row.title = body.title.trim();
    if (body.overrides && typeof body.overrides === "object") {
      row.layout = { ...row.layout, overrides: body.overrides as StoredResume["layout"]["overrides"] };
    }
    row.updatedAt = nowIso();
    return json({ item: publicResume(row, true) });
  }
  if (parts[0] === "resumes" && parts.length === 2 && method === "DELETE") {
    const blocked = disabled();
    if (blocked) return blocked;
    const row = findResume(parts[1]);
    if (!row) return json({ message: "Resume not found" }, 404);
    if (row.id === resumeState.templateResumeId) return json({ message: "The template resume cannot be deleted." }, 409);
    if (resumeState.applications.some((item) => item.resumeId === row.id)) {
      return json({ message: "This resume is used by a job application." }, 409);
    }
    resumeState.resumes = resumeState.resumes.filter((item) => item.id !== row.id);
    return json({ deleted: row.id });
  }
  if (parts[0] === "resumes" && parts.length === 3 && (parts[2] === "file" || parts[2] === "pdf") && method === "GET") {
    const row = findResume(parts[1]);
    if (!row) return json({ message: "Resume not found" }, 404);
    if (parts[2] === "pdf" && row.extract.status !== "ready") {
      return json({ message: "The resume is not ready yet." }, 409);
    }
    return fileBody(row, parts[2] === "pdf" ? "pdf" : "file");
  }
  if (parts[0] === "template" && method === "PUT") {
    const blocked = disabled();
    if (blocked) return blocked;
    const resumeId = String(body.resumeId ?? "");
    const row = findResume(resumeId);
    if (!row || row.format !== "docx" || row.extract.status !== "ready") {
      return json({ message: "Only a ready Word document can be the template." }, 409);
    }
    for (const other of resumeState.resumes) {
      if (other.id !== row.id && other.kind === "template") other.kind = "archive";
    }
    if (row.kind !== "tailored") row.kind = "template";
    resumeState.templateResumeId = row.id;
    return json({ templateResumeId: row.id });
  }
  if (parts[0] === "postings" && method === "GET") return json({ items: resumeState.postings });
  if (parts[0] === "postings" && method === "POST") {
    const blocked = disabled();
    if (blocked) return blocked;
    const created = addPosting(body);
    if (created instanceof Response) return created;
    return json({ item: created }, 201);
  }
  if (parts[0] === "tailor" && method === "POST") {
    const blocked = disabled();
    if (blocked) return blocked;
    const templateId = String(body.templateId ?? "") || resumeState.templateResumeId;
    const template = findResume(templateId);
    if (!template || template.format !== "docx" || template.extract.status !== "ready") {
      return json({ message: "Choose a ready Word template." }, 400);
    }
    let postingId = String(body.postingId ?? "");
    if (postingId) {
      if (!resumeState.postings.some((row) => row.id === postingId)) {
        return json({ message: "Job post not found." }, 404);
      }
    } else {
      const posting = body.posting;
      if (!posting || typeof posting !== "object") return json({ message: "Choose or paste a job post." }, 400);
      const created = addPosting(posting as Record<string, unknown>);
      if (created instanceof Response) return created;
      postingId = created.id;
    }
    const addToTracker = body.addToTracker !== false;
    const job = queueJob((current) => {
      const source = findResume(templateId);
      const posting = resumeState.postings.find((row) => row.id === postingId);
      if (!source || source.format !== "docx" || source.extract.status !== "ready" || !posting) {
        current.status = "failed";
        current.error = "Choose a ready Word template.";
        return;
      }
      const id = nextId("res");
      const findings = ["Rewrote the summary for this job post."];
      const paragraphs = source.paragraphs.map((row) =>
        row.id === "p2" ? { ...row, text: `Builds billing exports for ${posting.company}.`, chars: 24 + posting.company.length } : row,
      );
      const tailored: StoredResume = {
        id,
        title: `${posting.title} — ${posting.company}`,
        kind: "tailored",
        format: "docx",
        source: "tailor",
        file: { contentType: DOCX_TYPE, size: source.file.size },
        extract: { status: "ready", error: "" },
        derivedFrom: { templateId, postingId },
        createdAt: nowIso(),
        updatedAt: nowIso(),
        paragraphs,
        layout: layoutFor(paragraphs),
        generation: { model: resumeState.settings.model || resumeState.defaultModel, findings },
        dataBase64: source.dataBase64 || DOCX_B64,
      };
      resumeState.resumes = [tailored, ...resumeState.resumes];
      current.resumeIds = [id];
      current.findings = findings;
      if (addToTracker) {
        const application: JobApplication = {
          id: nextId("app"),
          resumeId: id,
          postingId,
          company: posting.company,
          position: posting.title,
          recruiter: { name: "", email: "", phone: "" },
          status: "saved",
          appliedAt: "",
          nextStepAt: "",
          notes: "",
          createdAt: nowIso(),
          updatedAt: nowIso(),
        };
        resumeState.applications = [application, ...resumeState.applications];
      }
    });
    return json({ job: publicJob(job) }, 202);
  }
  if (parts[0] === "applications" && parts.length === 1 && method === "GET") {
    return json({ items: resumeState.applications });
  }
  if (parts[0] === "applications" && parts.length === 1 && method === "POST") {
    const blocked = disabled();
    if (blocked) return blocked;
    const recruiter = recruiterOf(body.recruiter, { name: "", email: "", phone: "" });
    if (recruiter instanceof Response) return recruiter;
    const appliedAt = calendarDay(body.appliedAt, "Applied");
    if (appliedAt instanceof Response) return appliedAt;
    const nextStepAt = calendarDay(body.nextStepAt, "Next step");
    if (nextStepAt instanceof Response) return nextStepAt;
    const application: JobApplication = {
      id: nextId("app"),
      resumeId: String(body.resumeId ?? ""),
      postingId: String(body.postingId ?? ""),
      company: String(body.company ?? ""),
      position: String(body.position ?? ""),
      recruiter,
      status: String(body.status ?? "saved"),
      appliedAt,
      nextStepAt,
      notes: String(body.notes ?? ""),
      createdAt: nowIso(),
      updatedAt: nowIso(),
    };
    resumeState.applications = [application, ...resumeState.applications];
    return json({ item: application }, 201);
  }
  if (parts[0] === "applications" && parts.length === 2 && method === "PATCH") {
    const blocked = disabled();
    if (blocked) return blocked;
    const row = resumeState.applications.find((item) => item.id === parts[1]);
    if (!row) return json({ message: "Application not found" }, 404);
    const recruiter = recruiterOf(body.recruiter, row.recruiter);
    if (recruiter instanceof Response) return recruiter;
    const appliedAt = calendarDay(body.appliedAt ?? row.appliedAt, "Applied");
    if (appliedAt instanceof Response) return appliedAt;
    const nextStepAt = calendarDay(body.nextStepAt ?? row.nextStepAt, "Next step");
    if (nextStepAt instanceof Response) return nextStepAt;
    Object.assign(row, {
      company: body.company ?? row.company,
      position: body.position ?? row.position,
      status: body.status ?? row.status,
      resumeId: body.resumeId ?? row.resumeId,
      postingId: body.postingId ?? row.postingId,
      appliedAt,
      nextStepAt,
      notes: body.notes ?? row.notes,
      recruiter,
      updatedAt: nowIso(),
    });
    return json({ item: row });
  }
  if (parts[0] === "applications" && parts.length === 2 && method === "DELETE") {
    const blocked = disabled();
    if (blocked) return blocked;
    resumeState.applications = resumeState.applications.filter((item) => item.id !== parts[1]);
    return json({ deleted: parts[1] });
  }
  if (parts[0] === "jobs" && parts.length === 2 && method === "GET") {
    const job = resumeState.jobs.find((item) => item.jobId === parts[1]);
    if (!job) return json({ message: "Job not found" }, 404);
    return json({ job: publicJob(job) });
  }
  return null;
}
