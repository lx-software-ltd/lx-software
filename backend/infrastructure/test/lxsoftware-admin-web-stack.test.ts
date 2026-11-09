import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
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
};

describe("LxsoftwareAdminWebStack bucket policy", () => {
  let policies: Record<string, BucketPolicyResource>;
  let bucketLogicalId: string;
  let ownPolicyId: string;

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

    const logicalId = (construct: cdk.IResource) =>
      stack.getLogicalId(construct.node.defaultChild as cdk.CfnElement);
    bucketLogicalId = logicalId(stack.bucket);
    ownPolicyId = logicalId(stack.bucket.policy!);
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

  test("no other policy targets the origin bucket", () => {
    expect(policiesForOriginBucket()).toEqual([ownPolicyId]);
  });
});
