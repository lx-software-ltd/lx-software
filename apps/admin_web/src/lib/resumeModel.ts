export const DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
export const PDF_TYPE = "application/pdf";
export const MD_TYPE = "text/markdown";
export const TEXT_TYPE = "text/plain";

export const APPLICATION_STATUSES = [
  "saved",
  "applied",
  "screening",
  "interview",
  "offer",
  "rejected",
  "withdrawn",
] as const;

export const OUTPUT_LENGTHS = ["concise", "standard", "detailed"] as const;
export const REWRITE_SCOPE = ["headline", "summary", "bullets", "skills"] as const;
export const BULLET_POLICIES = ["keep", "flex"] as const;
export const PAGE_SIZES = ["A4", "Letter"] as const;

export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number];
export type OutputLength = (typeof OUTPUT_LENGTHS)[number];
export type RewriteScope = (typeof REWRITE_SCOPE)[number];
export type BulletPolicy = (typeof BULLET_POLICIES)[number];
export type PageSize = (typeof PAGE_SIZES)[number];

export type ResumeSettings = {
  model: string;
  maxUsdPerMonth: number;
  temperature: number;
  outputLength: OutputLength;
  rewriteScope: RewriteScope[];
  bulletPolicy: BulletPolicy;
  allowNewSkills: boolean;
  pageSize: PageSize;
  instructions: string;
};

export const DEFAULT_RESUME_SETTINGS: ResumeSettings = {
  model: "",
  maxUsdPerMonth: 5,
  temperature: 0.4,
  outputLength: "standard",
  rewriteScope: [...REWRITE_SCOPE],
  bulletPolicy: "keep",
  allowNewSkills: false,
  pageSize: "A4",
  instructions: "",
};

export const LOCKED_FACTS =
  "Contact, education, certifications, dates, employers, and titles stay as written. The model does not rewrite them.";

export type ResumeParagraph = {
  id: string;
  text: string;
  style: string;
  numbered: boolean;
  inTable: boolean;
  inTextBox: boolean;
  runs: number;
  chars: number;
};

export type ResumeLayout = {
  paragraphs: { id: string; role: string }[];
  roles: { headerId: string; bulletIds: string[] }[];
  overrides: Record<string, "locked" | "rewritable">;
};

export type ResumeSummary = {
  id: string;
  title: string;
  kind: string;
  format: string;
  source: string;
  file: { contentType: string; size: number };
  extract: { status: string; error: string };
  derivedFrom: { templateId?: string; postingId?: string } | null;
  createdAt: string;
  updatedAt: string;
};

export type ResumeDetail = ResumeSummary & {
  paragraphs: ResumeParagraph[];
  layout: ResumeLayout;
  generation: { model: string; findings: string[] } | null;
};

export type ResumeOverview = {
  enabled: boolean;
  settings: ResumeSettings;
  templateResumeId: string;
  defaultModel: string;
  spendUsdMonth: number;
  counts: { resumes: number; postings: number; applications: number };
  pdfCjk: boolean;
};

export type ResumeJob = {
  jobId: string;
  status: string;
  resumeIds: string[];
  error: string;
  findings: string[];
};

export type JobPosting = {
  id: string;
  title: string;
  company: string;
  url: string;
  location: string;
  adText: string;
  createdAt: string;
};

export type Recruiter = { name: string; email: string; phone: string };

export type JobApplication = {
  id: string;
  resumeId: string;
  postingId: string;
  company: string;
  position: string;
  recruiter: Recruiter;
  status: string;
  appliedAt: string;
  nextStepAt: string;
  notes: string;
  createdAt: string;
  updatedAt: string;
};

export type ResumeFileBody = {
  contentType: string;
  filename: string;
  dataBase64: string;
};

export function contentTypeForFile(name: string, browserType: string): string | null {
  const lower = name.toLowerCase();
  if (lower.endsWith(".doc") && !lower.endsWith(".docx")) return null;
  if (lower.endsWith(".docx") || browserType === DOCX_TYPE) return DOCX_TYPE;
  if (lower.endsWith(".pdf") || browserType === PDF_TYPE) return PDF_TYPE;
  if (lower.endsWith(".md") || lower.endsWith(".markdown")) return MD_TYPE;
  if (lower.endsWith(".txt") || browserType === TEXT_TYPE) return TEXT_TYPE;
  return null;
}

export function tailorProgress(status: string): string {
  if (status === "queued") return "Reading the job post…";
  if (status === "running") return "Rewriting paragraphs…";
  return "";
}

export function kindLabel(kind: string): string {
  if (kind === "template") return "Template";
  if (kind === "tailored") return "Tailored";
  return "Archive";
}

export function statusLabel(status: string): string {
  if (!status) return "";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function readFileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result ?? "");
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the file."));
    reader.readAsDataURL(file);
  });
}
