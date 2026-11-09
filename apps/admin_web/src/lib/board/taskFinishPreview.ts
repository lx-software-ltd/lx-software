const DEFAULT_LIMIT = 1600;

function clip(text: string, limit: number): string {
  if (text.length <= limit) return text;
  return `${text.slice(0, Math.max(0, limit - 40)).trimEnd()} … [truncated, ${text.length} chars]`;
}

/** Pretty-print a JSON deliverable and keep it short enough to sit under a title. */
export function prettyJsonText(body: string, limit = DEFAULT_LIMIT): string {
  const trimmed = body.trim();
  if (!trimmed) return "";
  let text = trimmed;
  try {
    text = JSON.stringify(JSON.parse(trimmed) as unknown, null, 2);
  } catch {
    text = trimmed;
  }
  return clip(text, limit);
}

function asRecord(args: unknown): Record<string, unknown> | null {
  if (!args) return null;
  if (typeof args === "string") {
    try {
      return asRecord(JSON.parse(args) as unknown);
    } catch {
      return null;
    }
  }
  if (typeof args === "object" && !Array.isArray(args)) return args as Record<string, unknown>;
  return null;
}

/** Preview of the JSON body a `task_finish` call delivered. Empty for other ops and for prose. */
export function taskFinishJsonPreview(op: string | undefined, args: unknown, limit = DEFAULT_LIMIT): string {
  if (op !== "task_finish") return "";
  const record = asRecord(args);
  if (!record) return "";
  const body = record.deliverable;
  if (typeof body !== "string" || !body.trim()) return "";
  const dtype = typeof record.deliverableType === "string" ? record.deliverableType : "";
  const trimmed = body.trim();
  const looksJson = dtype === "json" || dtype === "messages" || trimmed.startsWith("{") || trimmed.startsWith("[");
  if (!looksJson) return "";
  return prettyJsonText(trimmed, limit);
}

/** Server preview when the review snapshot has one; otherwise the deliverable still on the row. */
export function reviewFinishPreview(row: {
  readonly op?: string;
  readonly arguments?: unknown;
  readonly deliverablePreview?: string;
}): string {
  const direct = (row.deliverablePreview ?? "").trim();
  if (direct) return direct;
  return taskFinishJsonPreview(row.op, row.arguments);
}
