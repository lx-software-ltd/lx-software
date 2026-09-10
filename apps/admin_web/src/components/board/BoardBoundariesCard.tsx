import { useState } from "react";
import { AdminEditorSection } from "../ui";
import { BOARD_STAFF_ACTION_CLASSES } from "../../lib/contracts/generated";
import type { BoardBoundaries } from "../../lib/boardModel";

export type BoardBoundariesCardProps = {
  readonly boundaries: BoardBoundaries;
  readonly version?: number;
  readonly isSaving: boolean;
  readonly errorMessage?: string | null;
  readonly onSave: (boundaries: BoardBoundaries, version?: number) => void;
};

const HOLD_CLASSES = BOARD_STAFF_ACTION_CLASSES.filter((cls) => cls !== "never" && cls !== "code_production");

export function BoardBoundariesCard({ boundaries, version, isSaving, errorMessage, onSave }: BoardBoundariesCardProps) {
  const [draft, setDraft] = useState<BoardBoundaries>(boundaries);
  const queryStamp = `${version ?? ""}:${JSON.stringify(boundaries)}`;
  const [seenStamp, setSeenStamp] = useState(queryStamp);
  if (queryStamp !== seenStamp) {
    setSeenStamp(queryStamp);
    setDraft(boundaries);
  }
  const isDirty = JSON.stringify(draft) !== JSON.stringify(boundaries);

  return (
    <AdminEditorSection
      title="Boundaries"
      description="Hold windows, reply policy and escalation keywords. A hold of 0 hours means the write runs immediately when the member is at Act."
      footer={
        <>
          <button type="button" className="btn btn-primary" disabled={!isDirty || isSaving} onClick={() => onSave(draft, version)}>
            {isSaving ? "Saving…" : "Save boundaries"}
          </button>
          {errorMessage ? <span className="small text-danger">{errorMessage}</span> : null}
        </>
      }
    >
      <div className="row g-4">
        <div className="col-12 col-lg-6">
          <h3 className="h6">Hold windows (hours)</h3>
          <div className="table-responsive">
            <table className="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th>Class</th>
                  <th className="text-end">Hours</th>
                </tr>
              </thead>
              <tbody>
                {HOLD_CLASSES.map((cls) => (
                  <tr key={cls}>
                    <td>
                      <code>{cls}</code>
                    </td>
                    <td className="text-end" style={{ width: "7rem" }}>
                      <input
                        type="number"
                        min={0}
                        max={168}
                        className="form-control form-control-sm text-end"
                        value={draft.holds[cls] ?? 0}
                        onChange={(ev) =>
                          setDraft((d) => ({
                            ...d,
                            holds: { ...d.holds, [cls]: Number(ev.target.value) },
                          }))
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="col-12 col-lg-6">
          <h3 className="h6">Reply policy</h3>
          <label className="form-label small" htmlFor="board-reply-tone">
            Tone
          </label>
          <textarea
            id="board-reply-tone"
            className="form-control mb-2"
            rows={3}
            value={draft.reply.tone}
            onChange={(ev) => setDraft((d) => ({ ...d, reply: { ...d.reply, tone: ev.target.value } }))}
          />
          <div className="row g-2 mb-2">
            <div className="col-6">
              <label className="form-label small" htmlFor="board-quiet-start">
                Quiet start (HKT)
              </label>
              <input
                id="board-quiet-start"
                type="number"
                min={0}
                max={23}
                className="form-control"
                value={draft.reply.quietHoursHkt[0] ?? 22}
                onChange={(ev) =>
                  setDraft((d) => ({
                    ...d,
                    reply: { ...d.reply, quietHoursHkt: [Number(ev.target.value), d.reply.quietHoursHkt[1] ?? 8] },
                  }))
                }
              />
            </div>
            <div className="col-6">
              <label className="form-label small" htmlFor="board-quiet-end">
                Quiet end (HKT)
              </label>
              <input
                id="board-quiet-end"
                type="number"
                min={0}
                max={23}
                className="form-control"
                value={draft.reply.quietHoursHkt[1] ?? 8}
                onChange={(ev) =>
                  setDraft((d) => ({
                    ...d,
                    reply: { ...d.reply, quietHoursHkt: [d.reply.quietHoursHkt[0] ?? 22, Number(ev.target.value)] },
                  }))
                }
              />
            </div>
          </div>
          <label className="form-label small" htmlFor="board-max-thread">
            Max messages per thread per day
          </label>
          <input
            id="board-max-thread"
            type="number"
            min={1}
            max={20}
            className="form-control mb-3"
            value={draft.reply.maxMessagesPerThreadPerDay}
            onChange={(ev) =>
              setDraft((d) => ({
                ...d,
                reply: { ...d.reply, maxMessagesPerThreadPerDay: Number(ev.target.value) },
              }))
            }
          />
          <h3 className="h6">Escalation keywords</h3>
          <textarea
            id="board-escalation-keywords"
            className="form-control"
            rows={4}
            value={draft.escalation.keywords.join("\n")}
            onChange={(ev) =>
              setDraft((d) => ({
                ...d,
                escalation: {
                  ...d.escalation,
                  keywords: ev.target.value
                    .split("\n")
                    .map((line) => line.trim())
                    .filter(Boolean),
                },
              }))
            }
          />
          <div className="form-text">One keyword per line. Matched in English and Chinese.</div>
        </div>
      </div>
    </AdminEditorSection>
  );
}
