import { describe, expect, it } from "vitest";
import {
  DEFAULT_LINKEDIN_SETTINGS,
  guardrails,
  isLinkedInPostUrl,
  linkedInShareUrl,
  nextSlots,
} from "./linkedinModel";

describe("linkedin slots", () => {
  it("uses 08:30 HKT on Tuesday and Thursday", () => {
    const now = new Date("2026-10-05T02:00:00.000Z");
    const slots = nextSlots(DEFAULT_LINKEDIN_SETTINGS, now, 2);
    expect(slots[0]).toBe("2026-10-06T00:30:00.000Z");
    expect(slots[1]).toBe("2026-10-08T00:30:00.000Z");
  });

  it("skips a Tuesday slot that has already passed", () => {
    const now = new Date("2026-10-06T01:00:00.000Z");
    expect(nextSlots(DEFAULT_LINKEDIN_SETTINGS, now, 1)[0]).toBe("2026-10-08T00:30:00.000Z");
  });
});

describe("linkedin guardrails", () => {
  const settings = DEFAULT_LINKEDIN_SETTINGS;

  it("blocks the company name and a long first line", () => {
    expect(guardrails("Notes from LX Software.", "", [], settings).some((row) => row.code === "forbidden_word")).toBe(
      true,
    );
    expect(guardrails("x".repeat(211), "", [], settings).some((row) => row.code === "hook")).toBe(true);
  });

  it("accepts a linkedin.com post URL", () => {
    expect(isLinkedInPostUrl("https://www.linkedin.com/feed/update/urn:li:share:1")).toBe(true);
    expect(isLinkedInPostUrl("https://linkedin.com/posts/example")).toBe(true);
    expect(isLinkedInPostUrl("https://example.com/post")).toBe(false);
  });

  it("builds a share-box link from the post text", () => {
    expect(linkedInShareUrl("Hello")).toBe(
      "https://www.linkedin.com/feed/?shareActive=true&text=Hello",
    );
  });
});
