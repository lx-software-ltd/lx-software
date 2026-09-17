import { describe, expect, it } from "vitest";
import { defaultStatementBookTab } from "./StatementBookPage";

describe("defaultStatementBookTab", () => {
  it("opens Executive Board on Siu Tin Dei when no tab is requested", () => {
    expect(defaultStatementBookTab(true, "")).toBe("board");
    expect(defaultStatementBookTab(true, "?section=tasks&task=abc")).toBe("board");
    expect(defaultStatementBookTab(true, "?tab=board")).toBe("board");
  });

  it("honours an explicit book tab on Siu Tin Dei", () => {
    expect(defaultStatementBookTab(true, "?tab=dashboard")).toBe("dashboard");
    expect(defaultStatementBookTab(true, "?tab=expenses")).toBe("expenses");
    expect(defaultStatementBookTab(true, "?tab=gains")).toBe("gains");
  });

  it("keeps Dashboard as the default on books without an Executive Board", () => {
    expect(defaultStatementBookTab(false, "")).toBe("dashboard");
    expect(defaultStatementBookTab(false, "?tab=expenses")).toBe("expenses");
    expect(defaultStatementBookTab(false, "?tab=board")).toBe("dashboard");
  });
});
