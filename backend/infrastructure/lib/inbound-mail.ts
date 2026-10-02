import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as lambdaEventSources from "aws-cdk-lib/aws-lambda-event-sources";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as ses from "aws-cdk-lib/aws-ses";
import * as sesActions from "aws-cdk-lib/aws-ses-actions";
import type * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import type * as kms from "aws-cdk-lib/aws-kms";
import type * as sqs from "aws-cdk-lib/aws-sqs";
import { createPythonLambda } from "./constructs/python-lambda";
import { PARSE_TIMEOUTS } from "./shared-contracts";
import type { AdminParameters } from "./admin-parameters";
import { sesSendFromDomainStatement } from "./ses-send";
import { defineBoardMailSending, defineSharedReceiptRules } from "./inbound-mail-rules";

export interface InboundMailResources {
  readonly inboundMailBucket: s3.Bucket;
  readonly inboundReceiptRuleSet: ses.ReceiptRuleSet;
  readonly boardMailInboundAddress: string;
  readonly boardMailIdentity: ses.CfnEmailIdentity;
  readonly hasBoardMailSending: cdk.CfnCondition;
  readonly inboundStatementMailboxes: ReadonlyArray<{
    readonly localPart: string;
    readonly ownerKey: string;
    readonly displayLabel: string;
    readonly rawSegment?: string;
    readonly lineTypeOnly?: "income" | "expenditure";
  }>;
}

export function defineInboundMail(
  scope: cdk.Stack,
  deps: {
    readonly params: AdminParameters;
    readonly recordsTable: dynamodb.Table;
    readonly auditLogTable: dynamodb.Table;
    readonly assetsBucket: s3.Bucket;
    readonly sharedEncryptionKey: kms.IKey;
    readonly lambdaDeadLetterQueue: sqs.Queue;
    readonly adminFn: lambda.Function;
    readonly openRouterSecretPolicy: iam.Policy;
  },
): InboundMailResources {
  const {
    adminWebDomainName,
    googleClientId,
    googleClientSecret,
    adminFederatedEmailAllowlist,
    adminBootstrapEmail,
    adminBootstrapTempPassword,
    cognitoDomainPrefix,
    cognitoCustomDomainName,
    cognitoCustomDomainCertificateArn,
    openRouterApiKeySecretArn,
    openRouterModel,
    openRouterPdfEngine,
    enableBankingAppId,
    siutindeiClusterArn,
    siutindeiDbSecretArn,
    siutindeiDbSecretName,
    evolvesproutsClusterArn,
    evolvesproutsDbSecretArn,
    evolvesproutsDbSecretName,
    siutindeiAdminApiBaseUrl,
    siutindeiUserPoolId,
    boardImporterClientId,
    boardCatalogManagerId,
    boardCatalogImportEnabled,
    metaVerifyToken,
    metaPageId,
    metaIgUserId,
    metaWaPhoneNumberId,
    metaAdAccountId,
    metaWabaId,
    appStoreConnectAppId,
    appStoreConnectVendorNumber,
    googlePlayPackageName,
    ga4PropertyIds,
    gtmContainers,
    boardAwsStackPrefix,
    boardAwsLambdaNames,
    boardToolsEnabled,
    boardStaffEnabled,
    outreachSendingDomain,
    outreachFromLocalPart,
    publicSiteOrigins,
    publicApiBaseUrl,
    publicApiWritesEnabled,
    boardGitHubRepo,
    boardMailDomain,
    boardMailSendingEnabled,
    boardChatModel,
    boardMeetingModel,
    boardDeepDiveModel,
    inboundMailDomain,
    statementParseNotifyEmail,
    evolvesproutsInvoiceRecipient,
    evolvesproutsInvoiceReceiptRoleName,
  } = deps.params;
  const {
    recordsTable,
    auditLogTable,
    assetsBucket,
    sharedEncryptionKey,
    lambdaDeadLetterQueue,
    adminFn,
    openRouterSecretPolicy,
  } = deps;
  const adminStatementParseLambdaTimeout = cdk.Duration.seconds(
    PARSE_TIMEOUTS.lambdaTimeoutSeconds,
  );
  const openRouterHttpTimeoutSeconds = String(PARSE_TIMEOUTS.openRouterTimeoutSeconds);
  const parseJobStaleSeconds = String(PARSE_TIMEOUTS.parseJobStaleSeconds);
  const parseJobStuckSeconds = String(PARSE_TIMEOUTS.parseJobStuckSeconds);
  // ------------------------------------------------------------------
  // Inbound mail: SES → S3 (raw) → Lambda extracts PDF → same parser as UI
  // ------------------------------------------------------------------

  /**
   * Raw objects land at ``<inboundRawMailPrefix>/<houseKey>/…``. Lambda env
   * ``INBOUND_RAW_MAIL_PREFIX`` must match ``inboundRawMailPrefix``.
   */
  const inboundRawMailPrefix = "inbound-raw";

  /**
   * Map each inbox local-part to a finance owner key (house or statement
   * book). Display names differ from keys: "32 Hillmarton" uses
   * ``hillmarton``; The Morrison uses ``morrison``; LX Software expenses
   * use statement-book key ``lxSoftware``. S3 prefixes are lower-case
   * (``rawSegment``, defaulting to ``ownerKey``) because the Lambda
   * lower-cases the first path segment. ``billing@`` is the SES drop for
   * iCloud-forwarded ``billing@lx-software.com``.
   */
  type InboundStatementMailbox = {
    readonly localPart: string;
    readonly ownerKey: string;
    readonly displayLabel: string;
    readonly rawSegment?: string;
    readonly lineTypeOnly?: "income" | "expenditure";
  };
  const inboundStatementMailboxes: ReadonlyArray<InboundStatementMailbox> = [
    {
      localPart: "32-hillmarton",
      ownerKey: "hillmarton",
      displayLabel: "32 Hillmarton",
    },
    {
      localPart: "the-morrison",
      ownerKey: "morrison",
      displayLabel: "The Morrison",
    },
    {
      localPart: "billing",
      ownerKey: "lxSoftware",
      displayLabel: "LX Software",
      rawSegment: "lx-software",
      lineTypeOnly: "expenditure",
    },
  ];
  const inboundStatementMailboxEnv = JSON.stringify(
    inboundStatementMailboxes.map((mailbox) => ({
      segment: mailbox.rawSegment ?? mailbox.ownerKey,
      ownerKey: mailbox.ownerKey,
      ...(mailbox.lineTypeOnly ? { lineTypeOnly: mailbox.lineTypeOnly } : {}),
    }))
  );

  const inboundMailBucketName = [
    "lxsoftware-admin-inbound-mail",
    cdk.Aws.ACCOUNT_ID,
    cdk.Aws.REGION,
  ].join("-");

  const inboundMailBucket = new s3.Bucket(scope, "InboundMailBucket", {
    bucketName: inboundMailBucketName,
    blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    encryption: s3.BucketEncryption.S3_MANAGED,
    enforceSSL: true,
    versioned: true,
    removalPolicy: cdk.RemovalPolicy.RETAIN,
    lifecycleRules: [
      {
        id: "ExpireRawInboundMail",
        enabled: true,
        expiration: cdk.Duration.days(30),
        prefix: `${inboundRawMailPrefix}/`,
      },
    ],
  });

  const inboundStatementFn = createPythonLambda(scope, "InboundStatementMailFn", {
    entryDir: path.join(__dirname, "..", "..", "lambda", "admin"),
    handler: "inbound_email_handler.lambda_handler",
    timeout: adminStatementParseLambdaTimeout,
    memorySize: 1024,
    environmentEncryptionKey: sharedEncryptionKey,
    logEncryptionKey: sharedEncryptionKey,
    deadLetterQueue: lambdaDeadLetterQueue,
    environment: {
      RECORDS_TABLE_NAME: recordsTable.tableName,
      AUDIT_LOG_TABLE_NAME: auditLogTable.tableName,
      ASSETS_BUCKET_NAME: assetsBucket.bucketName,
      INBOUND_MAIL_BUCKET_NAME: inboundMailBucket.bucketName,
      INBOUND_RAW_MAIL_PREFIX: inboundRawMailPrefix,
      INBOUND_STATEMENT_MAILBOXES: inboundStatementMailboxEnv,
      INBOUND_AUDIT_USER_SUB: "inbound-email",
      // Inbound keeps handler-defaulted keys that AdminApiFn omits to stay
      // under the 4 KB environment cap (ASSET_MAX_BYTES, PARSE_JOB_TTL_SECONDS).
      ASSET_MAX_BYTES: String(20 * 1024 * 1024),
      OPENROUTER_API_KEY_SECRET_ARN: openRouterApiKeySecretArn.valueAsString,
      OPENROUTER_MODEL: openRouterModel.valueAsString,
      OPENROUTER_PDF_ENGINE: openRouterPdfEngine.valueAsString,
      OPENROUTER_TIMEOUT_SECONDS: openRouterHttpTimeoutSeconds,
      PARSE_WORKER_FUNCTION_NAME: adminFn.functionName,
      PARSE_JOB_STALE_SECONDS: parseJobStaleSeconds,
      PARSE_JOB_STUCK_SECONDS: parseJobStuckSeconds,
      PARSE_JOB_TTL_SECONDS: String(PARSE_TIMEOUTS.parseJobTtlSeconds),
    },
  });

  recordsTable.grantReadWriteData(inboundStatementFn);
  auditLogTable.grantReadWriteData(inboundStatementFn);
  assetsBucket.grantReadWrite(inboundStatementFn);
  inboundMailBucket.grantRead(inboundStatementFn);
  inboundMailBucket.grantDelete(inboundStatementFn);
  openRouterSecretPolicy.attachToRole(inboundStatementFn.role!);
  lambdaDeadLetterQueue.grantSendMessages(inboundStatementFn);

  adminFn.grantInvoke(inboundStatementFn);

  // AdminApiFn is invoked asynchronously for OpenRouter work (self-invoke from
  // the HTTP API + invoke from InboundStatementMailFn). A future split to
  // SQS + a dedicated parser Lambda would separate concurrency from API routes;
  // this stack keeps a single code bundle for low admin traffic.

  const inboundReceiptRuleSet = new ses.ReceiptRuleSet(scope, "InboundMailReceiptRuleSet", {
    receiptRuleSetName: "lxsoftware-inbound-mail",
  });

  for (const mailbox of inboundStatementMailboxes) {
    const rawSegment = mailbox.rawSegment ?? mailbox.ownerKey;
    const rawKeyPrefix = `${inboundRawMailPrefix}/${rawSegment}/`;

    inboundStatementFn.addEventSource(
      new lambdaEventSources.S3EventSource(inboundMailBucket, {
        events: [s3.EventType.OBJECT_CREATED],
        filters: [{ prefix: rawKeyPrefix }],
      })
    );

    inboundReceiptRuleSet.addRule(`InboundMailbox-${mailbox.ownerKey}`, {
      recipients: [
        cdk.Fn.join("", [mailbox.localPart, "@", inboundMailDomain.valueAsString]),
      ],
      enabled: true,
      actions: [
        new sesActions.S3({
          bucket: inboundMailBucket,
          objectKeyPrefix: rawKeyPrefix,
        }),
      ],
    });
  }

  // ------------------------------------------------------------------
  // Executive Board mail: every SiutindeiBoardMailDomain mailbox is copied here by a
  // Cloudflare Email Worker (scripts/cloudflare/siutindei-mail-fanout.js).
  // Same SES → S3 → InboundStatementMailFn path; the handler branches on the
  // ``inbound-raw/<boardMailRawSegment>/`` prefix into board_mail.py.
  // ------------------------------------------------------------------
  const boardMailLocalPart = "siutindei-board";
  const boardMailRawSegment = "siutindei";
  const boardMailRawKeyPrefix = `${inboundRawMailPrefix}/${boardMailRawSegment}/`;
  const boardMailInboundAddress = cdk.Fn.join("", [
    boardMailLocalPart,
    "@",
    inboundMailDomain.valueAsString,
  ]);

  inboundStatementFn.addEventSource(
    new lambdaEventSources.S3EventSource(inboundMailBucket, {
      events: [s3.EventType.OBJECT_CREATED],
      filters: [{ prefix: boardMailRawKeyPrefix }],
    })
  );
  inboundReceiptRuleSet.addRule("InboundMailbox-siutindei-board", {
    recipients: [boardMailInboundAddress],
    enabled: true,
    actions: [
      new sesActions.S3({
        bucket: inboundMailBucket,
        objectKeyPrefix: boardMailRawKeyPrefix,
      }),
    ],
  });

  defineSharedReceiptRules(scope, {
    inboundReceiptRuleSet,
    evolvesproutsInvoiceRecipient,
    evolvesproutsInvoiceReceiptRoleName,
  });


  for (const fn of [adminFn, inboundStatementFn]) {
    fn.addEnvironment("BOARD_MAIL_DOMAIN", boardMailDomain.valueAsString);
    fn.addEnvironment("BOARD_MAIL_RAW_SEGMENT", boardMailRawSegment);
    fn.addEnvironment("BOARD_MAIL_INBOUND_ADDRESS", boardMailInboundAddress);
  }
  // InboundStatementMailFn does not get these from buildAdminEnv. AdminApiFn
  // already has the same parameter tokens from that single assignment.
  inboundStatementFn.addEnvironment("BOARD_STAFF_ENABLED", boardStaffEnabled.valueAsString);
  inboundStatementFn.addEnvironment("BOARD_TOOLS_ENABLED", boardToolsEnabled.valueAsString);
  inboundStatementFn.addEnvironment(
    "BOARD_MAIL_SENDING_ENABLED",
    boardMailSendingEnabled.valueAsString,
  );
  inboundStatementFn.addEnvironment("OUTREACH_SENDING_DOMAIN", outreachSendingDomain.valueAsString);
  inboundStatementFn.addEnvironment(
    "OUTREACH_FROM_LOCAL_PART",
    outreachFromLocalPart.valueAsString,
  );

  adminFn.addEnvironment(
    "STATEMENT_PARSE_NOTIFY_EMAIL",
    statementParseNotifyEmail.valueAsString
  );
  adminFn.addEnvironment("INBOUND_MAIL_DOMAIN", inboundMailDomain.valueAsString);
  adminFn.addEnvironment(
    "STATEMENT_PARSE_NOTIFY_FROM",
    cdk.Fn.join("", ["statements@", inboundMailDomain.valueAsString])
  );
  const statementParseNotifyPolicy = new iam.Policy(
    scope,
    "StatementParseNotifySendPolicy",
    {
      statements: [sesSendFromDomainStatement(inboundMailDomain.valueAsString)],
    }
  );
  statementParseNotifyPolicy.attachToRole(adminFn.role!);

  const { boardMailIdentity, hasBoardMailSending } = defineBoardMailSending(scope, {
    adminFn,
    boardMailDomain,
    boardMailSendingEnabled,
  });
  return {
    inboundMailBucket,
    inboundReceiptRuleSet,
    boardMailInboundAddress,
    boardMailIdentity,
    hasBoardMailSending,
    inboundStatementMailboxes,
  };
}
