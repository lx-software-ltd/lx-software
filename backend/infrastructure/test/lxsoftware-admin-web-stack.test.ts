import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as s3 from "aws-cdk-lib/aws-s3";
import { LxsoftwareAdminWebStack } from "../lib/lxsoftware-admin-web-stack";

type Statement = {
  Sid?: string;
  Effect: string;
  Action: string | string[];
  Principal?: Record<string, unknown>;
  Condition?: Record<string, Record<string, unknown>>;
};

type BucketPolicyResource = {
  Properties: { Bucket: unknown; PolicyDocument: { Statement: Statement[] } };
  DeletionPolicy?: string;
  DependsOn?: string[];
};

describe("LxsoftwareAdminWebStack bucket policy", () => {
  let policies: Record<string, BucketPolicyResource>;
  let bucketLogicalId: string;
  let ownPolicyId: string;
  let legacyPolicyId: string;

  beforeAll(() => {
    const app = new cdk.App({
      context: { "aws:cdk:bundling-stacks": [] },
    });
    const stack = new LxsoftwareAdminWebStack(app, "lxsoftware-admin-web", {
      env: { account: "123456789012", region: "ap-southeast-1" },
      cspApiConnectOrigin:
        "https://example.execute-api.ap-southeast-1.amazonaws.com",
      cspAssetsConnectOrigins: "https://bucket.s3.amazonaws.com",
    });
    policies = Template.fromStack(stack).findResources(
      "AWS::S3::BucketPolicy",
    ) as Record<string, BucketPolicyResource>;

    const logicalId = (construct: cdk.IResource | s3.BucketPolicy) =>
      stack.getLogicalId(construct.node.defaultChild as cdk.CfnElement);
    bucketLogicalId = logicalId(stack.bucket);
    ownPolicyId = logicalId(stack.bucket.policy!);
    legacyPolicyId = logicalId(
      stack.node.findChild("AdminWebBucketPolicy") as s3.BucketPolicy,
    );
  });

  function policiesForOriginBucket(): string[] {
    return Object.entries(policies)
      .filter(([, res]) => (res.Properties.Bucket as { Ref: string }).Ref === bucketLogicalId)
      .map(([id]) => id)
      .sort();
  }

  test("the bucket's own policy carries both the HTTPS-only deny and the OAC read grant", () => {
    const statements = policies[ownPolicyId].Properties.PolicyDocument.Statement;

    const sslDeny = statements.find(
      (s) => s.Effect === "Deny" && s.Condition?.Bool?.["aws:SecureTransport"] === "false",
    );
    expect(sslDeny?.Action).toBe("s3:*");

    const oacRead = statements.find(
      (s) => s.Sid === "AllowCloudFrontServicePrincipalReadOnly",
    );
    expect(oacRead?.Effect).toBe("Allow");
    expect(oacRead?.Action).toBe("s3:GetObject");
    expect(oacRead?.Principal).toEqual({ Service: "cloudfront.amazonaws.com" });
    expect(oacRead?.Condition?.StringEquals?.["AWS:SourceArn"]).toBeDefined();
  });

  test("the legacy duplicate is retained so its later removal never calls DeleteBucketPolicy", () => {
    const legacy = policies[legacyPolicyId];
    expect(legacy.DeletionPolicy).toBe("Retain");
    expect(legacy.Properties.PolicyDocument.Statement).toHaveLength(1);
    expect(legacy.Properties.PolicyDocument.Statement[0].Sid).toBe(
      "AllowCloudFrontServicePrincipalReadOnly",
    );
  });

  test("the complete policy is applied after the legacy one", () => {
    expect(policies[ownPolicyId].DependsOn).toContain(legacyPolicyId);
  });

  test("no other policy targets the origin bucket", () => {
    expect(policiesForOriginBucket()).toEqual([ownPolicyId, legacyPolicyId].sort());
  });
});
