import { describe, expect, it } from "vitest";
import {
  DEFAULT_RESUME_SETTINGS,
  contentTypeForFile,
  kindLabel,
  tailorProgress,
} from "./resumeModel";

describe("resume model", () => {
  it("starts from the approved generation defaults", () => {
    expect(DEFAULT_RESUME_SETTINGS.maxUsdPerMonth).toBe(5);
    expect(DEFAULT_RESUME_SETTINGS.temperature).toBe(0.4);
    expect(DEFAULT_RESUME_SETTINGS.bulletPolicy).toBe("keep");
    expect(DEFAULT_RESUME_SETTINGS.allowNewSkills).toBe(false);
    expect(DEFAULT_RESUME_SETTINGS.rewriteScope).toEqual(["headline", "summary", "bullets", "skills"]);
  });

  it("accepts docx and rejects legacy doc", () => {
    expect(contentTypeForFile("Alex.docx", "")).toContain("wordprocessingml");
    expect(contentTypeForFile("Alex.doc", "application/msword")).toBeNull();
    expect(contentTypeForFile("notes.md", "")).toBe("text/markdown");
  });

  it("names the tailor stages", () => {
    expect(tailorProgress("queued")).toBe("Reading the job post…");
    expect(tailorProgress("running")).toBe("Rewriting paragraphs…");
    expect(kindLabel("template")).toBe("Template");
  });
});
