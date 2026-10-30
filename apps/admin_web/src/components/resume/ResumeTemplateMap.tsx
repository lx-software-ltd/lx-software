import type { ResumeDetail } from "../../lib/resumeModel";

export function ResumeTemplateMap({
  detail,
  overrides,
  onOverride,
  readOnly,
}: {
  readonly detail: ResumeDetail;
  readonly overrides: Record<string, "locked" | "rewritable">;
  readonly onOverride: (id: string, value: "locked" | "rewritable" | "") => void;
  readonly readOnly: boolean;
}) {
  const roles = new Map(detail.layout.paragraphs.map((row) => [row.id, row.role]));
  const paragraphs = detail.paragraphs.filter((row) => row.text.trim());
  if (paragraphs.length === 0) return <p className="small text-muted mb-0">No paragraphs yet.</p>;
  return (
    <ul className="list-unstyled mb-0 d-flex flex-column gap-2">
      {paragraphs.map((paragraph) => (
        <li key={paragraph.id} className="border rounded p-2">
          <div className="d-flex justify-content-between gap-2 align-items-center mb-1">
            <span className="small text-muted">{roles.get(paragraph.id) || "other"}</span>
            <select
              className="form-select form-select-sm w-auto"
              aria-label={`Lock ${paragraph.id}`}
              disabled={readOnly}
              value={overrides[paragraph.id] ?? ""}
              onChange={(event) =>
                onOverride(paragraph.id, event.target.value as "locked" | "rewritable" | "")
              }
            >
              <option value="">Role default</option>
              <option value="locked">Locked</option>
              <option value="rewritable">Rewritable</option>
            </select>
          </div>
          <p className="small mb-0">{paragraph.text}</p>
        </li>
      ))}
    </ul>
  );
}
