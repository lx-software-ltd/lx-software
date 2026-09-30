import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { PublicWebsiteStack } from "../lib/public-website-stack";

function directives(csp: string): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const part of csp.split(";")) {
    const [name, ...values] = part.trim().split(/\s+/);
    if (name) out.set(name, values);
  }
  return out;
}

describe("PublicWebsiteStack security headers", () => {
  let csp: Map<string, string[]>;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new PublicWebsiteStack(app, "lxsoftware-public-www", {
      env: { account: "123456789012", region: "us-east-1" },
    });
    const template = Template.fromStack(stack);
    const policies = template.findResources(
      "AWS::CloudFront::ResponseHeadersPolicy",
    );
    const [policy] = Object.values(policies);
    const value: string =
      policy.Properties.ResponseHeadersPolicyConfig.SecurityHeadersConfig
        .ContentSecurityPolicy.ContentSecurityPolicy;
    csp = directives(value);
  });

  test("allows Google Tag Manager and GA4 hosts", () => {
    const gtm = "https://www.googletagmanager.com";
    expect(csp.get("script-src")).toEqual(["'self'", gtm]);
    expect(csp.get("connect-src")).toEqual([
      "'self'",
      gtm,
      "https://*.google-analytics.com",
      "https://*.analytics.google.com",
    ]);
    expect(csp.get("img-src")).toEqual(
      expect.arrayContaining([gtm, "https://*.google-analytics.com"]),
    );
    expect(csp.get("frame-src")).toEqual(["'self'", gtm]);
  });

  test("keeps inline scripts, objects and framing blocked", () => {
    expect(csp.get("script-src")).not.toContain("'unsafe-inline'");
    expect(csp.get("script-src")).not.toContain("'unsafe-eval'");
    expect(csp.get("object-src")).toEqual(["'none'"]);
    expect(csp.get("frame-ancestors")).toEqual(["'none'"]);
    expect(csp.get("base-uri")).toEqual(["'self'"]);
  });
});
