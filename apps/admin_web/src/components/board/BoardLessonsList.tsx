import { useState } from "react";
import type { BoardLesson } from "../../lib/boardModel";

export type BoardLessonsListProps = {
  readonly lessons: readonly BoardLesson[];
  readonly isMutating?: boolean;
  readonly errorMessage?: string | null;
  readonly onConfirm: (lessonId: string, instruction?: string) => void;
  readonly onDismiss: (lessonId: string) => void;
};

export function BoardLessonsList({
  lessons,
  isMutating,
  errorMessage,
  onConfirm,
  onDismiss,
}: BoardLessonsListProps) {
  const [editId, setEditId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const pending = lessons.filter((l) => !l.confirmed && !l.dismissed);
  const confirmed = lessons.filter((l) => l.confirmed && !l.dismissed);

  return (
    <section className="card shadow-sm mb-4">
      <div className="card-body">
        <h3 className="h6">Lessons</h3>
        <p className="small text-muted">
          Vetoes, returns and &quot;this was wrong&quot; become standing instructions after you confirm them.
        </p>
        {pending.length === 0 && confirmed.length === 0 ? (
          <p className="small text-muted mb-0">No lessons yet.</p>
        ) : null}
        {pending.map((lesson) => (
          <div key={lesson.lessonId} className="border rounded p-2 mb-2">
            <div className="small text-muted">{lesson.kind} · {lesson.subject || "unscoped"} · {lesson.classKey}</div>
            <div className="small">{lesson.what}</div>
            {editId === lesson.lessonId ? (
              <textarea className="form-control form-control-sm mt-2" rows={2} value={draft} onChange={(ev) => setDraft(ev.target.value)} />
            ) : (
              <div className="mt-1">{lesson.instruction}</div>
            )}
            <div className="mt-2 d-flex gap-2">
              <button
                type="button"
                className="btn btn-sm btn-primary"
                disabled={isMutating}
                onClick={() => {
                  onConfirm(lesson.lessonId, editId === lesson.lessonId ? draft : undefined);
                  setEditId(null);
                }}
              >
                Confirm
              </button>
              <button
                type="button"
                className="btn btn-sm btn-outline-secondary"
                onClick={() => {
                  setEditId(lesson.lessonId);
                  setDraft(lesson.instruction);
                }}
              >
                Edit
              </button>
              <button type="button" className="btn btn-sm btn-link" disabled={isMutating} onClick={() => onDismiss(lesson.lessonId)}>
                Dismiss
              </button>
            </div>
          </div>
        ))}
        {confirmed.length > 0 ? (
          <details className="mt-2">
            <summary className="small">Confirmed ({confirmed.length})</summary>
            <ul className="small mb-0 mt-2">
              {confirmed.map((lesson) => (
                <li key={lesson.lessonId}>{lesson.instruction}</li>
              ))}
            </ul>
          </details>
        ) : null}
        {errorMessage ? <div className="small text-danger mt-2">{errorMessage}</div> : null}
      </div>
    </section>
  );
}
