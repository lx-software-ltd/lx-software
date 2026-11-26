import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { assemble } from "../bin/app";

function fnIfNames(value: unknown, found: Set<string>): void {
  if (Array.isArray(value)) {
    for (const item of value) {
      fnIfNames(item, found);
    }
    return;
  }
  if (value === null || typeof value !== "object") {
    return;
  }
  const record = value as Record<string, unknown>;
  const choice = record["Fn::If"];
  if (Array.isArray(choice) && typeof choice[0] === "string") {
    found.add(choice[0]);
  }
  for (const child of Object.values(record)) {
    fnIfNames(child, found);
  }
}

describe("assembled templates", () => {
  test("every Fn::If names a condition in the same template", () => {
    const app = new cdk.App({
      context: { "aws:cdk:bundling-stacks": [] },
    });
    assemble(app);
    const stacks = app.node.children.filter((child) => cdk.Stack.isStack(child));
    expect(stacks.map((stack) => stack.node.id).sort()).toEqual([
      "lxsoftware",
      "lxsoftware-admin-web",
      "lxsoftware-public-www",
    ]);
    for (const stack of stacks) {
      const json = Template.fromStack(stack).toJSON() as {
        Conditions?: Record<string, unknown>;
      };
      const named = new Set<string>();
      fnIfNames(json, named);
      const defined = new Set(Object.keys(json.Conditions ?? {}));
      const missing = [...named].filter((name) => !defined.has(name)).sort();
      expect({ stack: stack.node.id, missing }).toEqual({
        stack: stack.node.id,
        missing: [],
      });
    }
    const admin = stacks.find((stack) => stack.node.id === "lxsoftware-admin-web");
    const serialized = JSON.stringify(Template.fromStack(admin!).toJSON());
    expect(serialized).toContain("lxsoftware-AdminApiBaseUrl");
    expect(serialized).not.toContain("lxsoftware-CspApiExecuteApiOrigin");
    expect(serialized).not.toContain("UseApiCustomDomain");
  });
});
