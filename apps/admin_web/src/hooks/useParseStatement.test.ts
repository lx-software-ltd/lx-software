import { describe, expect, it } from "vitest";
import type { HouseFinanceData } from "../lib/financeModel";
import {
  existingImportedStatementBasenames,
  extractS3ErrorCode,
  statementImportResultMessage,
} from "./useParseStatement";

function minimalHouse(overrides: Partial<HouseFinanceData> = {}): HouseFinanceData {
  return {
    defaultCurrency: "HKD",
    float: { amount: 0, currency: "HKD" },
    lines: [],
    ...overrides,
  };
}

describe("extractS3ErrorCode", () => {
  it("returns null for an empty body", () => {
    expect(extractS3ErrorCode("")).toBeNull();
  });

  it("returns null when no <Code> tag is present", () => {
    expect(extractS3ErrorCode("<Error><Message>oops</Message></Error>")).toBeNull();
  });

  it("extracts the canonical S3 error code", () => {
    const xml =
      "<?xml version=\"1.0\" encoding=\"UTF-8\"?>" +
      "<Error><Code>EntityTooLarge</Code><Message>Your proposed upload exceeds the maximum allowed size</Message></Error>";
    expect(extractS3ErrorCode(xml)).toBe("EntityTooLarge");
  });

  it("trims surrounding whitespace inside the tag", () => {
    expect(
      extractS3ErrorCode("<Error><Code>\n  AccessDenied\n  </Code></Error>"),
    ).toBe("AccessDenied");
  });

  it("is case-insensitive on the tag name", () => {
    expect(extractS3ErrorCode("<error><code>NoSuchKey</code></error>")).toBe(
      "NoSuchKey",
    );
  });

  it("returns the first <Code> when several appear", () => {
    expect(
      extractS3ErrorCode(
        "<Error><Code>MalformedPOSTRequest</Code><Detail><Code>X</Code></Detail></Error>",
      ),
    ).toBe("MalformedPOSTRequest");
  });
});

describe("existingImportedStatementBasenames", () => {
  it("is empty when no lines have a source asset key", () => {
    const data = minimalHouse({
      lines: [
        {
          id: "1",
          dateUtc: "2026-01-01T00:00:00.000Z",
          type: "income",
          description: "Rent",
          netAmount: 1,
          vat: 0,
          grossAmount: 1,
          currency: "HKD",
        },
      ],
    });
    expect([...existingImportedStatementBasenames(data)]).toEqual([]);
  });

  it("collects basenames from each attachment key", () => {
    const data = minimalHouse({
      lines: [
        {
          id: "1",
          dateUtc: "2026-01-01T00:00:00.000Z",
          type: "expenditure",
          description: "A",
          netAmount: 1,
          vat: 0,
          grossAmount: 1,
          currency: "HKD",
          sourceAssetKeys: ["uploads/sub/abc/Bank.pdf"],
        },
        {
          id: "2",
          dateUtc: "2026-01-02T00:00:00.000Z",
          type: "expenditure",
          description: "B",
          netAmount: 2,
          vat: 0,
          grossAmount: 2,
          currency: "HKD",
          sourceAssetKeys: ["uploads/sub/xyz/Other.PDF"],
        },
      ],
    });
    const names = existingImportedStatementBasenames(data);
    expect(names.has("Bank.pdf")).toBe(true);
    expect(names.has("Other.PDF")).toBe(true);
    expect(names.has("uploads")).toBe(false);
  });

  it("collects basenames from every key when a line has multiple attachments", () => {
    const data = minimalHouse({
      lines: [
        {
          id: "1",
          dateUtc: "2026-01-01T00:00:00.000Z",
          type: "expenditure",
          description: "Split docs",
          netAmount: 1,
          vat: 0,
          grossAmount: 1,
          currency: "HKD",
          sourceAssetKeys: ["uploads/h1/part-a.pdf", "uploads/h2/part-b.PDF"],
        },
      ],
    });
    const names = existingImportedStatementBasenames(data);
    expect(names.has("part-a.pdf")).toBe(true);
    expect(names.has("part-b.PDF")).toBe(true);
  });

  it("excludes a line when excludeLineId matches", () => {
    const data = minimalHouse({
      lines: [
        {
          id: "keep",
          dateUtc: "2026-01-01T00:00:00.000Z",
          type: "expenditure",
          description: "A",
          netAmount: 1,
          vat: 0,
          grossAmount: 1,
          currency: "HKD",
          sourceAssetKeys: ["uploads/sub/abc/Dup.pdf"],
        },
        {
          id: "exclude-me",
          dateUtc: "2026-01-02T00:00:00.000Z",
          type: "expenditure",
          description: "B",
          netAmount: 2,
          vat: 0,
          grossAmount: 2,
          currency: "HKD",
          sourceAssetKeys: ["uploads/sub/xyz/Other.pdf"],
        },
      ],
    });
    expect([...existingImportedStatementBasenames(data, "exclude-me")]).toEqual([
      "Dup.pdf",
    ]);
  });
});

describe("statementImportResultMessage", () => {
  it("reports a normal import", () => {
    expect(statementImportResultMessage({ addedLines: 2, sourceAssetKeys: ["a.pdf"] })).toEqual({
      tone: "success",
      text: "Imported 2 statement lines.",
    });
  });

  it("warns when the exact file was already linked", () => {
    expect(
      statementImportResultMessage({
        addedLines: 0,
        sourceAssetKeys: ["inbound/owner/batch/note.pdf"],
        skippedExistingAssetKeys: ["inbound/owner/batch/note.pdf"],
        duplicateBasenameContent: "same",
      }),
    ).toEqual({
      tone: "warning",
      text: "This exact file is already linked to a statement line. No new lines were added.",
    });
  });

  it("warns when a repeated filename matches an earlier file", () => {
    expect(
      statementImportResultMessage({
        addedLines: 1,
        sourceAssetKeys: ["inbound/owner/new/note.pdf"],
        duplicateBasenames: ["note.pdf"],
        duplicateBasenameContent: "same",
      }).text,
    ).toContain("may already be on the statement");
  });

  it("warns when only the filename was repeated", () => {
    expect(
      statementImportResultMessage({
        addedLines: 1,
        sourceAssetKeys: ["uploads/new/note.pdf"],
        duplicateBasenames: ["note.pdf"],
        duplicateBasenameContent: "different",
      }).text,
    ).toContain("already imported");
  });
});
