import { describe, expect, it } from "vitest";
import { isRowExpandedParam } from "./expandedRecord";

describe("isRowExpandedParam", () => {
  it("keeps resume and application rows when their tab is open", () => {
    expect(isRowExpandedParam("resume")).toBe(true);
    expect(isRowExpandedParam("application")).toBe(true);
    expect(isRowExpandedParam("linkedin-post")).toBe(true);
    expect(isRowExpandedParam("section")).toBe(false);
  });
});
