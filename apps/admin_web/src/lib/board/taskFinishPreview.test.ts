import { describe, expect, it } from "vitest";
import { reviewFinishPreview, taskFinishJsonPreview } from "./taskFinishPreview";

describe("taskFinishJsonPreview", () => {
  it("pretty-prints a JSON deliverable and skips other finishes", () => {
    const args = {
      deliverableType: "json",
      deliverable: JSON.stringify({ district: "Eastern", organisations: [{ name_en: "Quarry Bay Park" }] }),
    };
    const preview = taskFinishJsonPreview("task_finish", args);
    expect(preview).toContain('"district": "Eastern"');
    expect(preview).toContain("Quarry Bay Park");
    expect(taskFinishJsonPreview("task_finish", { deliverableType: "markdown", deliverable: "# Notes" })).toBe("");
    expect(taskFinishJsonPreview("mail_reply", args)).toBe("");
  });

  it("clips a long JSON body", () => {
    const preview = taskFinishJsonPreview(
      "task_finish",
      { deliverableType: "json", deliverable: JSON.stringify({ note: "n".repeat(4000) }) },
      200,
    );
    expect(preview).toContain("[truncated,");
    expect(preview.length).toBeLessThan(280);
  });

  it("prefers the server preview on a review row", () => {
    const shown = reviewFinishPreview({
      op: "task_finish",
      deliverablePreview: '{\n  "district": "Eastern"\n}',
      arguments: JSON.stringify({ deliverableType: "json", deliverable: '{"district":"Other"}' }),
    });
    expect(shown).toContain("Eastern");
    expect(shown).not.toContain("Other");
    const fallback = reviewFinishPreview({
      op: "task_finish",
      arguments: JSON.stringify({ deliverableType: "json", deliverable: '{"district":"Eastern"}' }),
    });
    expect(fallback).toContain('"district": "Eastern"');
  });
});
