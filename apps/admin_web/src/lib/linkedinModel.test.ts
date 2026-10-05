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

  it("matches a blocked phrase only on a word boundary", () => {
    const allowed = guardrails("I hire mentors, and interimistic is not a status.", "", [], settings);
    expect(allowed.some((row) => row.code === "forbidden_word")).toBe(false);
    const blocked = guardrails("Please hire me. I am interim.", "", [], settings);
    const details = blocked.filter((row) => row.code === "forbidden_word").map((row) => row.detail);
    expect(details).toContain("Remove “hire me”.");
    expect(details).toContain("Remove “interim”.");
  });

  it("does not treat a bare number or #42 as a phone or hashtag", () => {
    const plain = guardrails("We served 10000000 requests. See issue #42.", "", [], settings);
    expect(plain.some((row) => row.code === "phone" || row.code === "hashtags")).toBe(false);
    expect(guardrails("Call +85212345678.", "", [], settings).some((row) => row.code === "phone")).toBe(true);
    expect(guardrails("Call 852 1234 5678.", "", [], settings).some((row) => row.code === "phone")).toBe(true);
    const tagged = guardrails("See #Architecture.", "", [], { ...settings, hashtagCap: 0 });
    expect(tagged.some((row) => row.code === "hashtags")).toBe(true);
  });
});
