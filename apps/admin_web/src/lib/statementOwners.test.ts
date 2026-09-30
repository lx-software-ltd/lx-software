import { describe, expect, it } from "vitest";
import { houseDisplayLabel } from "./houses";
import {
  isHouseKey,
  isStatementBookKey,
  kebabBookKey,
  parseStatementJobPath,
  parseStatementStartPath,
  statementBookApiPath,
  statementOwnerQueryKey,
  financeOwnerDisplayLabel,
  EVOLVE_SPROUTS_BOOK_KEY,
  LX_SOFTWARE_BOOK_KEY,
  SIU_TIN_DEI_BOOK_KEY,
  STATEMENT_BOOK_DASHBOARD_ORDER,
  isMirroredStatementBook,
} from "./statementOwners";

describe("statementOwners", () => {
  it("classifies house and book keys", () => {
    expect(isHouseKey("hillmarton")).toBe(true);
    expect(isHouseKey("siuTinDei")).toBe(false);
    expect(isHouseKey("lxSoftware")).toBe(false);
    expect(isStatementBookKey("siuTinDei")).toBe(true);
    expect(isStatementBookKey("lxSoftware")).toBe(true);
    expect(isStatementBookKey("evolveSprouts")).toBe(true);
    expect(isStatementBookKey("morrison")).toBe(false);
    expect(isMirroredStatementBook("evolveSprouts")).toBe(true);
    expect(isMirroredStatementBook("siuTinDei")).toBe(false);
  });

  it("builds parse paths for houses and statement books", () => {
    expect(parseStatementStartPath("hillmarton")).toBe(
      "/finance/hillmarton/parse-statement",
    );
    expect(parseStatementStartPath(SIU_TIN_DEI_BOOK_KEY)).toBe(
      "/siu-tin-dei/parse-statement",
    );
    expect(parseStatementJobPath(SIU_TIN_DEI_BOOK_KEY, "abc 1")).toBe(
      "/siu-tin-dei/parse-statement/jobs/abc%201",
    );
    expect(parseStatementStartPath(LX_SOFTWARE_BOOK_KEY)).toBe(
      "/lx-software/parse-statement",
    );
    expect(parseStatementJobPath(LX_SOFTWARE_BOOK_KEY, "abc 1")).toBe(
      "/lx-software/parse-statement/jobs/abc%201",
    );
  });

  it("uses a separate query key for each statement book", () => {
    expect(statementOwnerQueryKey("morrison")).toEqual(["finance"]);
    expect(statementOwnerQueryKey(SIU_TIN_DEI_BOOK_KEY)).toEqual(["siuTinDei"]);
    expect(statementOwnerQueryKey(LX_SOFTWARE_BOOK_KEY)).toEqual(["lxSoftware"]);
    expect(statementOwnerQueryKey(EVOLVE_SPROUTS_BOOK_KEY)).toEqual(["evolveSprouts"]);
  });

  it("maps camelCase book keys to kebab API slugs", () => {
    expect(kebabBookKey(SIU_TIN_DEI_BOOK_KEY)).toBe("siu-tin-dei");
    expect(kebabBookKey(LX_SOFTWARE_BOOK_KEY)).toBe("lx-software");
    expect(statementBookApiPath(LX_SOFTWARE_BOOK_KEY)).toBe("/lx-software");
    expect(kebabBookKey(EVOLVE_SPROUTS_BOOK_KEY)).toBe("evolve-sprouts");
    expect(statementBookApiPath(EVOLVE_SPROUTS_BOOK_KEY)).toBe("/evolve-sprouts");
    expect(STATEMENT_BOOK_DASHBOARD_ORDER).toEqual([
      "lxSoftware",
      "siuTinDei",
      "evolveSprouts",
    ]);
  });

  it("labels books for asset lists", () => {
    expect(financeOwnerDisplayLabel("siuTinDei")).toBe("Siu Tin Dei");
    expect(financeOwnerDisplayLabel("lxSoftware")).toBe("LX Software");
    expect(financeOwnerDisplayLabel("evolveSprouts")).toBe("Evolve Sprouts");
    expect(financeOwnerDisplayLabel("")).toBe("—");
    expect(houseDisplayLabel("siuTinDei")).toBe("Siu Tin Dei");
    expect(houseDisplayLabel("lxSoftware")).toBe("LX Software");
    expect(houseDisplayLabel("evolveSprouts")).toBe("Evolve Sprouts");
  });
});
