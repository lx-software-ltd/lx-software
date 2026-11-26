import * as cdk from "aws-cdk-lib";
import { LxsoftwareAdminWebStack } from "../lib/lxsoftware-admin-web-stack";
import { LxsoftwareStack } from "../lib/lxsoftware-stack";
import { PublicWebsiteStack } from "../lib/public-website-stack";
import { CheckovSuppressionAspect } from "../lib/constructs/checkov-suppressions";

// Centralized tagging — applied to every resource in every stack that
// supports tagging. Keep tag *keys* stable; rotating keys forces a churn
// across every supported AWS resource.
const COMMON_TAGS: Record<string, string> = {
  Organization: "LX Software",
  Repository: "lx-software",
  Environment: "production",
  ManagedBy: "CDK",
};

/**
 * Tag a stack with its name + a logical Component / Project so cost reports
 * can group by stack or by product surface.
 */
function tagStack(stack: cdk.Stack, project: string, component: string) {
  cdk.Tags.of(stack).add("Project", project);
  cdk.Tags.of(stack).add("Component", component);
  cdk.Tags.of(stack).add("Stack", stack.stackName);
}

/** Build the three stacks. Tests call this; `cdk` runs it below. */
export function assemble(app: cdk.App): cdk.App {
  for (const [k, v] of Object.entries(COMMON_TAGS)) {
    cdk.Tags.of(app).add(k, v);
  }

  const bootstrapQualifier = process.env.CDK_BOOTSTRAP_QUALIFIER;
  if (bootstrapQualifier) {
    app.node.setContext("@aws-cdk/core:bootstrapQualifier", bootstrapQualifier);
  }

  const synthesizer = bootstrapQualifier
    ? new cdk.DefaultStackSynthesizer({ qualifier: bootstrapQualifier })
    : undefined;

  const env = {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  };

  // 1) Public marketing website (S3 + CloudFront).
  const publicWeb = new PublicWebsiteStack(app, "lxsoftware-public-www", {
    description: "LX Software public marketing website (S3 + CloudFront).",
    env,
    synthesizer,
  });
  tagStack(publicWeb, "Public Website", "marketing-site");

  // 2) Consolidated admin backend (Cognito + DynamoDB + S3 assets + HTTP API).
  const lxsoftware = new LxsoftwareStack(app, "lxsoftware", {
    description:
      "LX Software admin backend: Cognito user pool, DynamoDB tables, private uploads bucket, and HTTP API.",
    env,
    synthesizer,
  });
  tagStack(lxsoftware, "Admin Console", "backend");

  // 3) Admin SPA delivery (S3 + CloudFront + WAF/CSP).
  //
  // The admin SPA uploads PDF statements directly to the private assets
  // bucket via presigned POST. The browser must be allowed to `fetch()` the
  // bucket S3 hostname under our CloudFront CSP, so we pass both the legacy
  // global virtual-hosted endpoint and the regional one — the Python admin
  // Lambda (default boto3 config) currently signs the legacy form, but a
  // future SDK upgrade may switch to the regional one. Allow-listing both
  // avoids a Safari "Load failed" / Chrome "Failed to fetch" the moment the
  // SDK changes its mind.
  const adminWeb = new LxsoftwareAdminWebStack(app, "lxsoftware-admin-web", {
    description: "LX Software admin SPA delivery (S3 + CloudFront).",
    env,
    synthesizer,
    // Import the origin the API stack already resolved. Passing
    // cspApiConnectOrigin copies its Fn::If, and this template does not
    // define UseApiCustomDomain. This stack lists that one origin.
    cspApiConnectOrigin: cdk.Fn.importValue("lxsoftware-AdminApiBaseUrl"),
    cspAssetsConnectOrigins: cdk.Fn.join(" ", [
      cdk.Fn.join("", ["https://", lxsoftware.assetsBucket.bucketDomainName]),
      cdk.Fn.join("", [
        "https://",
        lxsoftware.assetsBucket.bucketRegionalDomainName,
      ]),
    ]),
  });
  tagStack(adminWeb, "Admin Console", "spa");
  adminWeb.addDependency(lxsoftware);

  // Inject Checkov skip metadata onto CDK-internal resources (AwsCustomResource
  // and BucketNotifications Lambdas) plus VPC suppression for application
  // Lambdas. The Security Scanning workflow filters these inSource SARIF
  // suppressions out before uploading to GitHub Code Scanning.
  cdk.Aspects.of(app).add(new CheckovSuppressionAspect());
  return app;
}

if (process.env.JEST_WORKER_ID === undefined) {
  assemble(new cdk.App());
}
