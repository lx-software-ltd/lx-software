const DEFAULT_LIMIT = 1600;

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? "";
}

function shrinkJson(value: unknown, budget: number, depth = 0): unknown {
  if (depth > 8) return "…";
  if (pretty(value).length <= budget) return value;
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const kept: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      const trial = { ...kept, [key]: item };
      if (pretty(trial).length <= budget) {
        kept[key] = item;
        continue;
      }
      if (item && (typeof item === "object" || typeof item === "string")) {
        const shrunk = shrinkJson(item, Math.max(20, budget - pretty(kept).length - key.length - 8), depth + 1);
        const nested = { ...kept, [key]: shrunk };
        if (shrunk !== item && pretty(nested).length <= budget) kept[key] = shrunk;
      }
      break;
    }
    return kept;
  }
  if (Array.isArray(value)) {
    const kept: unknown[] = [];
    for (const item of value) {
      const trial = [...kept, item];
      if (pretty(trial).length <= budget) {
        kept.push(item);
        continue;
      }
      if (item && (typeof item === "object" || typeof item === "string")) {
        const shrunk = shrinkJson(item, Math.max(20, Math.floor(budget / 2)), depth + 1);
        const nested = [...kept, shrunk];
        if (shrunk !== item && pretty(nested).length <= budget) kept.push(shrunk);
      }
      break;
    }
    return kept;
  }
  if (typeof value === "string") {
    let lo = 0;
    let hi = value.length;
    let best = "";
    while (lo <= hi) {
      const mid = Math.floor((lo + hi) / 2);
      const candidate = `${value.slice(0, mid)}…`;
      if (JSON.stringify(candidate).length <= budget) {
        best = candidate;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return best;
  }
  return value;
}

function boundedPretty(value: unknown, limit: number): string {
  const full = pretty(value);
  if (full.length <= limit) return full;
  const note = `\n… [truncated, ${full.length} chars]`;
  let budget = Math.max(20, limit - note.length);
  let body = pretty(shrinkJson(value, budget));
  for (let i = 0; i < 6 && body.length + note.length > limit; i += 1) {
    budget = Math.max(20, Math.floor(budget * 0.7));
    body = pretty(shrinkJson(value, budget));
  }
  return body + note;
}

function clipText(text: string, limit: number): string {
  if (text.length <= limit) return text;
  const note = `\n… [truncated, ${text.length} chars]`;
  let cut = text.slice(0, Math.max(0, limit - note.length));
  const newline = cut.lastIndexOf("\n");
  if (newline >= cut.length / 2) cut = cut.slice(0, newline);
  return `${cut.trimEnd()}${note}`;
}

/** Pretty-print a JSON deliverable. A long body stays valid JSON plus a truncation line. */
export function prettyJsonText(body: string, limit = DEFAULT_LIMIT): string {
  const trimmed = body.trim();
  if (!trimmed) return "";
  try {
    return boundedPretty(JSON.parse(trimmed) as unknown, limit);
  } catch {
    return clipText(trimmed, limit);
  }
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
