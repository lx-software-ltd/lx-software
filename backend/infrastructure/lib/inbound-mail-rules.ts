import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import type * as lambda from "aws-cdk-lib/aws-lambda";
import * as ses from "aws-cdk-lib/aws-ses";
import * as cr from "aws-cdk-lib/custom-resources";
import { sesSendFromDomainStatement } from "./ses-send";

/**
 * Evolve Sprouts invoice receipt rule plus activation of the shared rule set.
 * Construct ids stay InboundMailbox-evolvesprouts-invoices and
 * ActivateInboundMailReceiptRuleSet.
 */
export function defineSharedReceiptRules(
  scope: cdk.Stack,
  input: {
    readonly inboundReceiptRuleSet: ses.ReceiptRuleSet;
    readonly evolvesproutsInvoiceRecipient: cdk.CfnParameter;
    readonly evolvesproutsInvoiceReceiptRoleName: cdk.CfnParameter;
  },
) {
  const {
    inboundReceiptRuleSet,
    evolvesproutsInvoiceRecipient,
    evolvesproutsInvoiceReceiptRoleName,
  } = input;
  // ------------------------------------------------------------------
  // Evolve Sprouts invoices share this rule set. SES allows only one
  // active receipt rule set per region; the evolvesprouts stack used to
  // create and activate its own set, which hid hillmarton + board mail.
  // The ES processor / bucket / SNS topic stay in that repo. This rule
  // keeps the same SES receipt-rule name so ES bucket/role/KMS policies
  // can allow both SourceArns during the cutover.
  // ------------------------------------------------------------------
  // Coupled to the evolvesprouts stack, which is not in this repo: the receipt
  // role, SNS topic, and assets bucket keep their physical names. Fn.importValue
  // cannot see that stack's exports from here.
  const evolvesproutsInvoiceRuleName = "evolvesprouts-inbound-invoice-email-rule";
  const evolvesproutsInvoiceRawPrefix = "inbound-email/raw/";
  const evolvesproutsAssetsBucketName = cdk.Fn.join("-", [
    "evolvesprouts-assets",
    cdk.Aws.ACCOUNT_ID,
    cdk.Aws.REGION,
  ]);
  const evolvesproutsInvoiceTopicArn = cdk.Stack.of(scope).formatArn({
    service: "sns",
    resource: "evolvesprouts-inbound-invoice-email-events",
  });
  const evolvesproutsInvoiceReceiptRoleArn = cdk.Stack.of(scope).formatArn({
    service: "iam",
    region: "",
    resource: "role",
    resourceName: evolvesproutsInvoiceReceiptRoleName.valueAsString,
  });

  const evolvesproutsInvoiceRule = new ses.CfnReceiptRule(
    scope,
    "InboundMailbox-evolvesprouts-invoices",
    {
      ruleSetName: inboundReceiptRuleSet.receiptRuleSetName,
      rule: {
        name: evolvesproutsInvoiceRuleName,
        enabled: true,
        scanEnabled: true,
        tlsPolicy: "Optional",
        recipients: [evolvesproutsInvoiceRecipient.valueAsString],
        actions: [
          {
            s3Action: {
              bucketName: evolvesproutsAssetsBucketName,
              objectKeyPrefix: evolvesproutsInvoiceRawPrefix,
              topicArn: evolvesproutsInvoiceTopicArn,
              iamRoleArn: evolvesproutsInvoiceReceiptRoleArn,
            },
          },
        ],
      },
    }
  );
  evolvesproutsInvoiceRule.node.addDependency(inboundReceiptRuleSet);

  const activateInboundMailRuleSet = new cr.AwsCustomResource(
    scope,
    "ActivateInboundMailReceiptRuleSet",
    {
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ["ses:SetActiveReceiptRuleSet"],
          resources: ["*"],
        }),
      ]),
      installLatestAwsSdk: false,
      onCreate: {
        service: "SES",
        action: "setActiveReceiptRuleSet",
        parameters: {
          RuleSetName: inboundReceiptRuleSet.receiptRuleSetName,
        },
        physicalResourceId: cr.PhysicalResourceId.of(
          "lxsoftware-inbound-mail-active"
        ),
      },
      onUpdate: {
        service: "SES",
        action: "setActiveReceiptRuleSet",
        parameters: {
          RuleSetName: inboundReceiptRuleSet.receiptRuleSetName,
        },
        physicalResourceId: cr.PhysicalResourceId.of(
          "lxsoftware-inbound-mail-active"
        ),
      },
    }
  );
  activateInboundMailRuleSet.node.addDependency(inboundReceiptRuleSet);
  activateInboundMailRuleSet.node.addDependency(evolvesproutsInvoiceRule);
}

/** Board sending identity and SES read/send policy. Created only when mail sending is enabled. */
export function defineBoardMailSending(
  scope: cdk.Stack,
  input: {
    readonly adminFn: lambda.Function;
    readonly boardMailDomain: cdk.CfnParameter;
    readonly boardMailSendingEnabled: cdk.CfnParameter;
  },
) {
  const { adminFn, boardMailDomain, boardMailSendingEnabled } = input;
  // Sending identity for SiutindeiBoardMailDomain, created only once the owner flips
  // SiutindeiBoardMailSendingEnabled (DNS must carry the DKIM CNAMEs first). The send
  // policy is scoped to that single identity so the board can never send
  // from anything but the company domain.
  const hasBoardMailSending = new cdk.CfnCondition(scope, "HasSiutindeiBoardMailSending", {
    expression: cdk.Fn.conditionEquals(
      boardMailSendingEnabled.valueAsString,
      "true"
    ),
  });
  const boardMailIdentity = new ses.CfnEmailIdentity(scope, "SiutindeiBoardMailSendingIdentity", {
    emailIdentity: boardMailDomain.valueAsString,
    dkimAttributes: { signingEnabled: true },
    // Custom MAIL FROM so SPF aligns with header_from. Without it, SES uses
    // *.amazonses.com as the envelope and DMARC SPF always fails; a single
    // domain-DKIM miss then quarantines under p=quarantine.
    mailFromAttributes: {
      mailFromDomain: cdk.Fn.join(".", ["mail", boardMailDomain.valueAsString]),
      behaviorOnMxFailure: "USE_DEFAULT_VALUE",
    },
  });
  boardMailIdentity.cfnOptions.condition = hasBoardMailSending;
  const boardMailSendPolicy = new iam.Policy(scope, "SiutindeiBoardMailSendPolicy", {
      statements: [
        sesSendFromDomainStatement(boardMailDomain.valueAsString),
        // Mail header health: is the identity verified, are we out of the
        // sandbox. GetAccount only supports Resource *.
        new iam.PolicyStatement({
          actions: ["ses:GetEmailIdentity"],
          resources: [
            cdk.Stack.of(scope).formatArn({
              service: "ses",
              resource: "identity",
              resourceName: boardMailDomain.valueAsString,
            }),
          ],
        }),
        new iam.PolicyStatement({
          actions: ["ses:GetAccount"],
          resources: ["*"],
        }),
        new iam.PolicyStatement({
          actions: ["ses:CreateEmailTemplate", "ses:GetEmailTemplate", "ses:UpdateEmailTemplate"],
          resources: [
            cdk.Stack.of(scope).formatArn({
              service: "ses",
              resource: "template",
              resourceName: "lxsoftware-admin-siutindei-*",
            }),
          ],
        }),
      ],
  });
  boardMailSendPolicy.attachToRole(adminFn.role!);
  const cfnBoardMailSendPolicy = boardMailSendPolicy.node.defaultChild as iam.CfnPolicy;
  cfnBoardMailSendPolicy.cfnOptions.condition = hasBoardMailSending;
  return { boardMailIdentity, hasBoardMailSending };
}
