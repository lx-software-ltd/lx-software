import * as cdk from "aws-cdk-lib";
import type * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import type * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import type * as kms from "aws-cdk-lib/aws-kms";
import type * as s3 from "aws-cdk-lib/aws-s3";
import type * as ses from "aws-cdk-lib/aws-ses";
import type { AuthConstruct } from "./constructs/auth";
import type { InboundMailResources } from "./inbound-mail";

export function defineAdminOutputs(
  scope: cdk.Stack,
  deps: {
    readonly auth: AuthConstruct;
    readonly recordsTable: dynamodb.Table;
    readonly auditLogTable: dynamodb.Table;
    readonly assetsBucket: s3.Bucket;
    readonly httpApi: apigwv2.HttpApi;
    readonly inboundMailDomain: cdk.CfnParameter;
    readonly evolvesproutsInvoiceRecipient: cdk.CfnParameter;
    readonly enableBankingSigningKey: kms.Key;
    readonly outreachSendingIdentity: ses.CfnEmailIdentity;
  } & InboundMailResources,
): void {
  const {
    auth,
    recordsTable,
    auditLogTable,
    assetsBucket,
    httpApi,
    inboundMailDomain,
    inboundStatementMailboxes,
    inboundReceiptRuleSet,
    evolvesproutsInvoiceRecipient,
    inboundMailBucket,
    boardMailInboundAddress,
    boardMailIdentity,
    hasBoardMailSending,
    outreachSendingIdentity,
    enableBankingSigningKey,
  } = deps;

  // ------------------------------------------------------------------
  // CloudFormation outputs (export names kept stable for compatibility
  // with downstream consumers / dashboards / runbooks).
  // ------------------------------------------------------------------
  new cdk.CfnOutput(scope, "UserPoolId", {
    value: auth.userPool.userPoolId,
    exportName: "lxsoftware-UserPoolId",
  });

  new cdk.CfnOutput(scope, "UserPoolClientId", {
    value: auth.userPoolClient.userPoolClientId,
    exportName: "lxsoftware-UserPoolClientId",
  });

  new cdk.CfnOutput(scope, "UserPoolArn", {
    value: auth.userPool.userPoolArn,
    exportName: "lxsoftware-UserPoolArn",
  });

  new cdk.CfnOutput(scope, "CognitoDomain", {
    value: auth.cognitoOAuthBaseUrl,
    description: "Full https URL for Cognito hosted UI / OAuth.",
    exportName: "lxsoftware-CognitoDomain",
  });

  const cognitoCustomDomainCloudFront = new cdk.CfnOutput(
    scope,
    "CognitoCustomDomainCloudFront",
    {
      value: auth.cognitoCustomHostedDomain.attrCloudFrontDistribution,
      description:
        "CNAME target for the Cognito custom Hosted UI domain (ACM + DNS).",
      exportName: "lxsoftware-CognitoCustomDomainCloudFront",
    },
  );
  cognitoCustomDomainCloudFront.condition = auth.useCustomAuthDomain;

  new cdk.CfnOutput(scope, "RecordsTableName", {
    value: recordsTable.tableName,
    exportName: "lxsoftware-RecordsTableName",
  });

  new cdk.CfnOutput(scope, "RecordsTableArn", {
    value: recordsTable.tableArn,
    exportName: "lxsoftware-RecordsTableArn",
  });

  new cdk.CfnOutput(scope, "AuditLogTableName", {
    value: auditLogTable.tableName,
    exportName: "lxsoftware-AuditLogTableName",
  });

  new cdk.CfnOutput(scope, "AuditLogTableArn", {
    value: auditLogTable.tableArn,
    exportName: "lxsoftware-AuditLogTableArn",
  });

  new cdk.CfnOutput(scope, "AssetsBucketName", {
    value: assetsBucket.bucketName,
    exportName: "lxsoftware-AssetsBucketName",
  });

  new cdk.CfnOutput(scope, "AssetsBucketArn", {
    value: assetsBucket.bucketArn,
    exportName: "lxsoftware-AssetsBucketArn",
  });

  for (const mailbox of inboundStatementMailboxes) {
    const suffix = mailbox.ownerKey.replace(/[^a-zA-Z0-9]/g, "");
    const displayHint =
      mailbox.lineTypeOnly === "expenditure"
        ? `Expense PDF inbox for "${mailbox.displayLabel}"`
        : `Statement PDF inbox for "${mailbox.displayLabel}"`;
    const forwardHint =
      mailbox.localPart === "billing"
        ? " Forward billing@lx-software.com (iCloud) here."
        : "";
    new cdk.CfnOutput(scope, `InboundMailboxAddress${suffix}`, {
      value: cdk.Fn.join("", [mailbox.localPart, "@", inboundMailDomain.valueAsString]),
      description: `${displayHint}; DDB/API key is "${mailbox.ownerKey}".${forwardHint}`,
      exportName: `lxsoftware-InboundMailbox-${mailbox.ownerKey}`,
    });
  }

  new cdk.CfnOutput(scope, "InboundMailReceiptRuleSetName", {
    value: inboundReceiptRuleSet.receiptRuleSetName,
    description:
      "Shared SES receipt rule set (hillmarton, morrison, LX Software billing, siutindei-board, Evolve Sprouts invoices). This stack sets it active on deploy.",
    exportName: "lxsoftware-InboundMailReceiptRuleSetName",
  });

  new cdk.CfnOutput(scope, "EvolvesproutsInboundInvoiceAddress", {
    value: evolvesproutsInvoiceRecipient.valueAsString,
    description:
      "Invoice mailbox hosted on the shared lxsoftware-inbound-mail rule set; raw MIME still lands in the Evolve Sprouts assets bucket.",
    exportName: "lxsoftware-EvolvesproutsInboundInvoiceAddress",
  });

  new cdk.CfnOutput(scope, "InboundMailMxTarget", {
    value: cdk.Fn.join("", ["inbound-smtp.", cdk.Aws.REGION, ".amazonaws.com"]),
    description: "MX record hostname (use priority 10) for the inbound mail domain.",
    exportName: "lxsoftware-InboundMailMxTarget",
  });

  new cdk.CfnOutput(scope, "InboundMailBucketName", {
    value: inboundMailBucket.bucketName,
    description: "S3 bucket where SES stores raw inbound messages before processing.",
    exportName: "lxsoftware-InboundMailBucketName",
  });

  new cdk.CfnOutput(scope, "SiutindeiBoardMailInboundAddress", {
    value: boardMailInboundAddress,
    description:
      "Destination the Cloudflare Email Worker forwards every SiutindeiBoardMailDomain message to (verify it once in Cloudflare; the verification mail lands in the inbound bucket).",
    exportName: "lxsoftware-SiutindeiBoardMailInboundAddress",
  });

  for (const n of [1, 2, 3] as const) {
    const output = new cdk.CfnOutput(scope, `SiutindeiBoardMailDkimCname${n}`, {
      value: cdk.Fn.join(" CNAME ", [
        boardMailIdentity.getAtt(`DkimDNSTokenName${n}`).toString(),
        boardMailIdentity.getAtt(`DkimDNSTokenValue${n}`).toString(),
      ]),
      description: `DKIM CNAME ${n} of 3 to add to the SiutindeiBoardMailDomain zone (name CNAME value).`,
    });
    output.condition = hasBoardMailSending;
  }

  for (const n of [1, 2, 3] as const) {
    new cdk.CfnOutput(scope, `SiutindeiOutreachDkimCname${n}`, {
      value: cdk.Fn.join(" CNAME ", [
        outreachSendingIdentity.getAtt(`DkimDNSTokenName${n}`).toString(),
        outreachSendingIdentity.getAtt(`DkimDNSTokenValue${n}`).toString(),
      ]),
      description: `DKIM CNAME ${n} of 3 to add to the SiutindeiBoardOutreachSendingDomain zone (name CNAME value). DNS-only; after FAILED, retry SES then run scripts/sync-ses-sending-dns.py.`,
    });
  }

  new cdk.CfnOutput(scope, "EnableBankingSigningKeyId", {
    value: enableBankingSigningKey.keyId,
    description:
      "KMS key id whose public key must be registered with Enable Banking " +
      "(export the PEM with aws kms get-public-key; see docs/deployment/admin-website.md).",
    exportName: "lxsoftware-EnableBankingSigningKeyId",
  });

  new cdk.CfnOutput(scope, "AdminApiBaseUrl", {
    value: httpApi.apiEndpoint,
    description: "Invoke URL for the admin HTTP API.",
    exportName: "lxsoftware-AdminApiBaseUrl",
  });
}
