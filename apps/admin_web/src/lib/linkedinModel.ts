/** Personal LinkedIn drafts. Keep the checks aligned with linkedin_store.py. */

export const HOOK_MAX = 210;
export const BODY_MAX = 3000;
export const COMMENT_MAX = 1250;
export const COMMENTARY_MAX = 3000;

export const BUILTIN_FORBIDDEN = [
  "lx software",
  "lx-software",
  "lxsoftware",
  "interim",
  "available immediately",
  "open to work",
  "looking for work",
  "hire me",
] as const;

export const PRODUCT_PHRASES = [
  "siu tin dei",
  "siutindei",
  "evolve sprouts",
  "evolvesprouts",
] as const;

export const LINKEDIN_PILLARS = [
  { id: "architecture", label: "Architecture decisions" },
  { id: "leadership", label: "Engineering leadership" },
  { id: "platforms", label: "Cloud and platforms" },
  { id: "ai-practice", label: "AI in practice" },
  { id: "delivery", label: "Lessons from delivery" },
  { id: "questions", label: "Questions I get asked" },
] as const;

export const WEEKDAY_OPTIONS = [
  { id: 0, label: "Monday" },
  { id: 1, label: "Tuesday" },
  { id: 2, label: "Wednesday" },
  { id: 3, label: "Thursday" },
  { id: 4, label: "Friday" },
  { id: 5, label: "Saturday" },
  { id: 6, label: "Sunday" },
] as const;

export type LinkedInGuardrail = {
  readonly code: string;
  readonly severity: "error" | "warn";
  readonly detail: string;
};

export type LinkedInDraftSettings = {
  postsPerWeek: number;
  weekdays: number[];
  slotHour: number;
  slotMinute: number;
  draftsPerGeneration: number;
  voiceNotes: string;
  styleExample: string;
  forbiddenWords: string[];
  hashtagCap: number;
  linksInFirstComment: boolean;
  allowProductMentions: boolean;
  maxUsdPerMonth: number;
  notifyEmail: string;
  model: string;
  pillars: string[];
  imagesEnabled: boolean;
  imageModel: string;
  imageFormat: string;
  imageStyle: string;
  imageCharacter: string;
};

export type LinkedInOrganization = {
  id: string;
  name: string;
};

export type LinkedInConnection = {
  status: string;
  channel: string;
  memberName: string;
  organizationId: string;
  organizationName: string;
  organizations: LinkedInOrganization[];
  tokenExpiresAt: string;
  includeOrganizations: boolean;
  appConfigured: boolean;
  appStatus: string;
};

export type LinkedInMetrics = {
  reactions: number;
  comments: number;
  impressions: number | null;
  pulledAt?: string;
  unavailable?: boolean;
};

const COMMENTARY_RESERVED = new Set("\\()[]{}@|~_<>*".split(""));

function escapeCommentarySegment(text: string): string {
  let out = "";
  for (const char of text) {
    if (COMMENTARY_RESERVED.has(char)) out += "\\";
    out += char;
  }
  return out;
}

/** Little-text escaping that leaves URLs and hashtags untouched. Mirrors linkedin_api.escape_commentary. */
export function escapeCommentary(text: string): string {
  const protectedText = /https?:\/\/\S+|#[^\s#]+/g;
  let out = "";
  let last = 0;
  for (const match of text.matchAll(protectedText)) {
    const index = match.index ?? 0;
    out += escapeCommentarySegment(text.slice(last, index));
    out += match[0];
    last = index + match[0].length;
  }
  return out + escapeCommentarySegment(text.slice(last));
}

/** Post body as LinkedIn will receive it, including hashtags that are not already in the text. */
export function renderedCommentary(body: string, hashtags: readonly string[]): string {
  let text = body.trim();
  const folded = text.toLowerCase();
  const extras: string[] = [];
  for (const tag of hashtags) {
    const cleaned = tag.trim().replace(/^#/, "");
    if (!cleaned) continue;
    const token = `#${cleaned}`;
    if (!folded.includes(token.toLowerCase())) extras.push(token);
  }
  if (extras.length > 0) text = `${text}\n\n${extras.join(" ")}`;
  return escapeCommentary(text);
}

/** How soon the stored LinkedIn access expires. */
export function linkedInAccessState(iso: string, now = Date.now()): "ok" | "soon" | "expired" | null {
  if (!iso) return null;
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return null;
  const hours = (at - now) / 3_600_000;
  if (hours < 0) return "expired";
  if (hours < 48) return "soon";
  return "ok";
}

export type LinkedInImage = {
  contentType?: string;
  status?: string;
  scene?: string;
  caption?: string;
  expression?: string;
  error?: string;
  model?: string;
  /** A scene / expression / caption rewrite in the worker. */
  brief?: { status?: string; error?: string };
};

export type LinkedInCharacter = {
  photo: { contentType: string } | null;
  sheet: { contentType: string } | null;
  candidates: { id: string; contentType: string }[];
};

export type LinkedInPost = {
  postId: string;
  status: string;
  channel: string;
  pillar: string;
  ideaId: string;
  seedId?: string;
  body: string;
  firstComment: string;
  hashtags: string[];
  slotAt: string;
  guardrails: LinkedInGuardrail[];
  generation?: { model?: string; jobId?: string; voiceHash?: string } | null;
  platform?: { url?: string; publishedAt?: string; urn?: string } | null;
  manual?: { url?: string; postedAt?: string } | null;
  image?: LinkedInImage | null;
  imageNote?: string;
  metrics?: LinkedInMetrics | null;
  publishError?: string;
  createdAt?: string;
  updatedAt?: string;
};

export type LinkedInIdea = {
  ideaId: string;
  text: string;
  pillar: string;
  status: string;
  usedBy: string;
  createdAt?: string;
};

export type LinkedInOverview = {
  enabled: boolean;
  publishEnabled: boolean;
  settings: LinkedInDraftSettings;
  pillars: readonly { id: string; label: string }[];
  connection: LinkedInConnection;
  counts: { drafted: number; approved: number; published: number; ideas: number };
  spendUsdMonth: number;
  nextSlots: string[];
  builtinForbidden: string[];
  defaultModel: string;
  recommendedVoice?: string;
  styleExampleMax?: number;
  defaultImageModel?: string;
  imageModelAlternative?: string;
  recommendedImageStyle?: string;
  imageStyleMax?: number;
  imageCharacterMax?: number;
};

export const SAMPLE_LINKEDIN_POSTS: LinkedInPost[] = [
  {
    postId: "li_hook",
    status: "drafted",
    channel: "profile",
    pillar: "architecture",
    ideaId: "",
    body: "A rollback is a design decision.\n\nWrite the path back before the path forward.",
    firstComment: "",
    hashtags: ["Architecture"],
    slotAt: "",
    guardrails: [],
    image: {
      contentType: "image/png",
      status: "ready",
      scene: "In a lift, the author holds a plan that only points one way.",
      caption: "I wrote the way back first.",
      expression: "deadpan",
      error: "",
      model: "bytedance-seed/seedream-4.5",
    },
  },
  {
    postId: "li_posted",
    status: "published",
    channel: "profile",
    pillar: "delivery",
    ideaId: "",
    body: "The review that caught the outage started with one question.\n\nWhat would we page someone for?",
    firstComment: "",
    hashtags: [],
    slotAt: "2026-09-29T00:30:00.000Z",
    guardrails: [],
    platform: {
      url: "https://www.linkedin.com/feed/update/urn:li:share:1",
      publishedAt: "2026-09-29T00:30:00.000Z",
      urn: "urn:li:share:1",
    },
    metrics: { reactions: 4, comments: 1, impressions: null },
  },
];

export const SAMPLE_LINKEDIN_IDEAS: LinkedInIdea[] = [
  {
    ideaId: "idea_rollback",
    text: "A rollback that took longer than the change.",
    pillar: "delivery",
    status: "new",
    usedBy: "",
  },
];

/** Mirrors `RECOMMENDED_VOICE` in `backend/lambda/admin/linkedin_store.py`. */
export const RECOMMENDED_LINKEDIN_VOICE =
  "First person singular, always I, never we. Conversational, as if I were telling a former colleague over lunch what I have been building. No hook: the first line is plain and specific to this story, not a question, not a claim. Tell it in the order it happened: what I noticed, what I decided, what I built, where it broke, where it stands now. Name the real constraint (a full-time job, nights and weekends, a month of evenings) and real figures when I have them. Plain dashes for a short list. One-line paragraphs are fine. Dry, understated, a little self-deprecating; an aside now and then. Admit what is unfinished and what might fail. No sensationalism, no wow, no lesson headline, no moral, no call to action. Each post has its own shape: a different way in and a different way out from the last one, no stock opening line, no stock closing line, no catchphrase carried from post to post. Usually 200 to 450 words.";

/** Mirrors `STYLE_EXAMPLE_MAX` in `linkedin_store.py`. The default example itself comes from the API. */
export const STYLE_EXAMPLE_MAX = 3000;

/** Mirrors `DEFAULT_IMAGE_MODEL` and `RECOMMENDED_IMAGE_STYLE` in `linkedin_store.py`. */
export const DEFAULT_IMAGE_MODEL = "bytedance-seed/seedream-4.5";
export const IMAGE_MODEL_ALTERNATIVE = "qwen/qwen-image-3";
export const IMAGE_FORMATS = [
  { id: "square", label: "Square, 1200 × 1200" },
  { id: "portrait", label: "Portrait, 1080 × 1350" },
  { id: "wide", label: "Wide, 1200 × 675" },
] as const;
export const RECOMMENDED_IMAGE_STYLE =
  "Single-panel magazine gag cartoon. Black ink line art on white paper, dense cross-hatching for shadow, no grey wash, no colour. Faces are caricatures, not portraits: simplified features, bold outlines, flat white skin with hatching only in shadow. A detailed room, one man mid-action. No lettering and no logos. One two-word label is allowed when the scene needs it, such as a door sign or a folder tab; screens are unreadable scribbles.";
export const DEFAULT_IMAGE_CHARACTER =
  "A man in his thirties with short dark hair, side-parted, clean-shaven, a round face, wearing a light striped button-down shirt with an open collar.";

/** Fixture only. The server default is the owner's own post (`STYLE_EXAMPLE` in `linkedin_store.py`). */
const SAMPLE_STYLE_EXAMPLE =
  "Here is about the week I spent on a 20 KB limit.\n\nI had added one more route to the admin API and the deploy failed. Not the code, the permissions.\n\nSo I read the error properly...\n\nI know what you're thinking - this is in the docs. Yes. I had not read that page.";

export const DEFAULT_LINKEDIN_SETTINGS: LinkedInDraftSettings = {
  postsPerWeek: 2,
  weekdays: [1, 3],
  slotHour: 8,
  slotMinute: 30,
  draftsPerGeneration: 4,
  voiceNotes: RECOMMENDED_LINKEDIN_VOICE,
  styleExample: SAMPLE_STYLE_EXAMPLE,
  forbiddenWords: [],
  hashtagCap: 3,
  linksInFirstComment: false,
  allowProductMentions: false,
  maxUsdPerMonth: 5,
  notifyEmail: "",
  model: "",
  pillars: LINKEDIN_PILLARS.map((row) => row.id),
  imagesEnabled: true,
  imageModel: DEFAULT_IMAGE_MODEL,
  imageFormat: "square",
  imageStyle: RECOMMENDED_IMAGE_STYLE,
  imageCharacter: DEFAULT_IMAGE_CHARACTER,
};

export function pillarLabel(id: string): string {
  return LINKEDIN_PILLARS.find((row) => row.id === id)?.label ?? id;
}

export function hookText(body: string): string {
  return body.trim().split("\n", 1)[0]?.trim() ?? "";
}

export function linkedInShareUrl(body: string): string {
  return `https://www.linkedin.com/feed/?shareActive=true&text=${encodeURIComponent(body)}`;
}

export function postUrl(post: LinkedInPost): string {
  return post.platform?.url || post.manual?.url || "";
}

export function isLinkedInPostUrl(url: string): boolean {
  const link = url.trim();
  return link.startsWith("https://www.linkedin.com/") || link.startsWith("https://linkedin.com/");
}

function terms(
  settings: Pick<
    LinkedInDraftSettings,
    "forbiddenWords"
  >,
): string[] {
  const extra = settings.forbiddenWords.map((word) => word.trim().toLowerCase()).filter(Boolean);
  return [...new Set([...BUILTIN_FORBIDDEN, ...extra])];
}

function containsTerm(haystack: string, term: string): boolean {
  if (!term) return false;
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?<![\\w])${escaped}(?![\\w])`).test(haystack);
}

function hasPhone(text: string): boolean {
  if (/\+\d{8,15}/.test(text)) return true;
  for (const match of text.matchAll(/(?:\d[\s.\-()]*){8,}/g)) {
    const chunk = match[0] ?? "";
    const digits = chunk.replace(/\D/g, "");
    if (digits.length >= 8 && digits.length <= 15 && /\d[\s.\-()]+\d/.test(chunk)) return true;
  }
  return false;
}

export function guardrails(
  body: string,
  comment: string,
  hashtags: readonly string[],
  settings: Pick<
    LinkedInDraftSettings,
    "forbiddenWords" | "allowProductMentions" | "hashtagCap" | "linksInFirstComment"
  >,
): LinkedInGuardrail[] {
  const findings: LinkedInGuardrail[] = [];
  const hook = hookText(body);
  if (!hook) {
    findings.push({ code: "hook", severity: "error", detail: "The first line is empty." });
  } else if (hook.length > HOOK_MAX) {
    findings.push({
      code: "hook",
      severity: "error",
      detail: `The first line is ${hook.length} characters. Keep it within ${HOOK_MAX}.`,
    });
  }
  if (body.length > BODY_MAX) {
    findings.push({
      code: "too_long",
      severity: "error",
      detail: `The post is ${body.length} characters. The limit is ${BODY_MAX}.`,
    });
  } else if (body.trim()) {
    const rendered = renderedCommentary(body, hashtags);
    if (rendered.length > COMMENTARY_MAX) {
      findings.push({
        code: "too_long",
        severity: "error",
        detail: `The post is ${rendered.length} characters after hashtags and formatting. LinkedIn allows ${COMMENTARY_MAX}.`,
      });
    }
  }
  if (comment.length > COMMENT_MAX) {
    findings.push({
      code: "comment",
      severity: "error",
      detail: `The first comment is over ${COMMENT_MAX} characters.`,
    });
  }
  const haystack = `${body}\n${comment}`.toLowerCase();
  for (const term of terms(settings)) {
    if (containsTerm(haystack, term)) {
      findings.push({ code: "forbidden_word", severity: "error", detail: `Remove “${term}”.` });
    }
  }
  if (!settings.allowProductMentions) {
    for (const term of PRODUCT_PHRASES) {
      if (containsTerm(haystack, term)) {
        findings.push({
          code: "product_mention",
          severity: "error",
          detail: `Remove the product mention “${term}”.`,
        });
      }
    }
  }
  const inline = [...body.matchAll(/#([A-Za-z][\w]{0,39})/g)].map((match) => match[1] ?? "");
  const tags = hashtags.map((tag) => tag.replace(/^#/, "").trim()).filter(Boolean);
  const unique = new Set([...tags, ...inline]);
  if (unique.size > settings.hashtagCap) {
    findings.push({
      code: "hashtags",
      severity: "error",
      detail: `Use at most ${settings.hashtagCap} hashtags.`,
    });
  }
  if (/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i.test(body + comment)) {
    findings.push({ code: "email", severity: "error", detail: "Remove the email address." });
  }
  if (hasPhone(body + comment)) {
    findings.push({ code: "phone", severity: "error", detail: "Remove the phone number." });
  }
  if (/(https?:\/\/|www\.)\S+/i.test(body)) {
    findings.push({
      code: "url_in_body",
      severity: settings.linksInFirstComment ? "error" : "warn",
      detail: "A link in the post body is easy to miss. Put it in the first comment.",
    });
  }
  return findings;
}

export function hasBlockingGuardrail(findings: readonly LinkedInGuardrail[]): boolean {
  return findings.some((row) => row.severity === "error");
}

const HKT_OFFSET_MS = 8 * 60 * 60 * 1000;

function hktParts(instant: Date): { year: number; month: number; day: number; weekday: number } {
  const shifted = new Date(instant.getTime() + HKT_OFFSET_MS);
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
    weekday: (shifted.getUTCDay() + 6) % 7,
  };
}

function slotInstant(year: number, month: number, day: number, hour: number, minute: number): Date {
  return new Date(Date.UTC(year, month - 1, day, hour - 8, minute, 0, 0));
}

function isoWeek(year: number, month: number, day: number): string {
  const date = new Date(Date.UTC(year, month - 1, day));
  const dayNum = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - dayNum + 3);
  const isoYear = date.getUTCFullYear();
  const firstThursday = new Date(Date.UTC(isoYear, 0, 4));
  const firstDay = (firstThursday.getUTCDay() + 6) % 7;
  firstThursday.setUTCDate(firstThursday.getUTCDate() - firstDay + 3);
  const week = 1 + Math.round((date.getTime() - firstThursday.getTime()) / 604800000);
  return `${isoYear}-${week}`;
}

/** Upcoming 08:30 HKT slots (or the saved hour) as UTC timestamps. */
export function nextSlots(
  settings: Pick<LinkedInDraftSettings, "weekdays" | "postsPerWeek" | "slotHour" | "slotMinute">,
  now: Date,
  count: number,
  taken: ReadonlySet<string> = new Set(),
): string[] {
  const weekdays = new Set(settings.weekdays);
  const perWeek = settings.postsPerWeek;
  const used = new Map<string, number>();
  for (const stamp of taken) {
    const parsed = new Date(stamp);
    if (Number.isNaN(parsed.getTime())) continue;
    const parts = hktParts(parsed);
    const key = isoWeek(parts.year, parts.month, parts.day);
    used.set(key, (used.get(key) ?? 0) + 1);
  }
  const out: string[] = [];
  const start = hktParts(now);
  const cursor = new Date(Date.UTC(start.year, start.month - 1, start.day));
  for (let offset = 0; offset < 120 && out.length < count; offset += 1) {
    const day = new Date(cursor.getTime() + offset * 86400000);
    const year = day.getUTCFullYear();
    const month = day.getUTCMonth() + 1;
    const date = day.getUTCDate();
    const weekday = (day.getUTCDay() + 6) % 7;
    if (!weekdays.has(weekday)) continue;
    const slot = slotInstant(year, month, date, settings.slotHour, settings.slotMinute);
    if (slot.getTime() <= now.getTime()) continue;
    const key = isoWeek(year, month, date);
    if ((used.get(key) ?? 0) >= perWeek) continue;
    const stamp = slot.toISOString();
    if (taken.has(stamp)) continue;
    used.set(key, (used.get(key) ?? 0) + 1);
    out.push(stamp);
  }
  return out;
}
