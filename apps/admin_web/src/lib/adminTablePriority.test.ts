import { describe, expect, it } from "vitest";
import { adminColumnClass, adminColumnPriorityClass } from "./adminTablePriority";

describe("adminColumnPriorityClass", () => {
  it("keeps primary columns visible at every breakpoint", () => {
    expect(adminColumnPriorityClass("primary")).toBe("");
    expect(adminColumnPriorityClass()).toBe("");
  });

  it("marks secondary columns for hiding below md", () => {
    expect(adminColumnPriorityClass("secondary")).toBe("admin-col-secondary");
  });

  it("marks tertiary columns for hiding below lg", () => {
    expect(adminColumnPriorityClass("tertiary")).toBe("admin-col-tertiary");
  });
});

describe("adminColumnClass", () => {
  it("marks the operations column so its header can collapse on phones", () => {
    expect(adminColumnClass({ key: "ops" })).toBe("admin-col-ops");
    expect(adminColumnClass({ key: "ops", priority: "secondary" })).toBe("admin-col-ops");
  });

  it("keeps priority classes for every other column", () => {
    expect(adminColumnClass({ key: "name" })).toBe("");
    expect(adminColumnClass({ key: "extra", priority: "secondary" })).toBe("admin-col-secondary");
  });
});
