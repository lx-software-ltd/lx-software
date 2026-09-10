import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import {
  HttpJwtAuthorizer,
  HttpLambdaAuthorizer,
  HttpLambdaResponseType,
} from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as events from "aws-cdk-lib/aws-events";
import * as eventsTargets from "aws-cdk-lib/aws-events-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as lambdaEventSources from "aws-cdk-lib/aws-lambda-event-sources";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as scheduler from "aws-cdk-lib/aws-scheduler";
import * as schedulerTargets from "aws-cdk-lib/aws-scheduler-targets";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as ses from "aws-cdk-lib/aws-ses";
import * as sesActions from "aws-cdk-lib/aws-ses-actions";
import * as sns from "aws-cdk-lib/aws-sns";
import * as snsSubs from "aws-cdk-lib/aws-sns-subscriptions";
import * as sqs from "aws-cdk-lib/aws-sqs";
import * as cr from "aws-cdk-lib/custom-resources";
import type { Construct } from "constructs";
import { AuthConstruct } from "./constructs/auth";
import { createPythonLambda } from "./constructs/python-lambda";
import { ADMIN_WEB_HOSTNAME, PARSE_TIMEOUTS } from "./shared-contracts";

/**
 * Lambda proxy integration that does NOT add an `AWS::Lambda::Permission`
 * per route. `HttpLambdaIntegration` grants API Gateway invoke rights one
 * route at a time, and with 60+ routes on one function those statements
 * pushed the function's resource-based policy past Lambda's fixed 20 KB
 * limit ("The final policy size (20525) is bigger than the limit (20480)").
 *
 * The stack instead grants a single API-wide permission — see
 * `AdminApiInvoke` below — whose statement is deliberately short so it fits
 * next to the legacy per-route statements during the deployment that
 * removes them (CloudFormation creates before it deletes).
 */
const ASC_KEY_TEMPLATE = {
  keyId: "REPLACE_ME",
  issuerId: "REPLACE_ME",
  appId: "",
  vendorNumber: "",
};
const PLAY_SA_TEMPLATE = {
  client_email: "REPLACE_ME@example.iam.gserviceaccount.com",
  packageName: "",
};
const ANALYTICS_SA_TEMPLATE = {
  client_email: "REPLACE_ME@example.iam.gserviceaccount.com",
};

type BoardConnectorSecrets = {
  github: secretsmanager.ISecret;
  search: secretsmanager.ISecret;
  metaToken: secretsmanager.ISecret;
  metaAppSecret: secretsmanager.ISecret;
  appStore: secretsmanager.ISecret;
  play: secretsmanager.ISecret;
  analytics: secretsmanager.ISecret;
};

/**
 * Placeholder secret the owner overwrites in the Secrets Manager console.
 * CloudFormation only writes GenerateSecretString on create (or if this
 * construct's generator properties change), so later CDK deploys keep the
 * real value. RETAIN so a stack delete does not wipe a filled-in token.
 */
function boardPlaceholderSecret(
  scope: Construct,
  id: string,
  props: {
    secretName: string;
    description: string;
    encryptionKey: kms.IKey;
    tenant: string;
    purpose: string;
    jsonTemplate?: Record<string, string>;
    generateKey?: string;
  }
): secretsmanager.Secret {
  const generator: secretsmanager.SecretStringGenerator = props.jsonTemplate
    ? {
        secretStringTemplate: JSON.stringify(props.jsonTemplate),
        generateStringKey: props.generateKey ?? "token",
        excludePunctuation: true,
        passwordLength: 40,
      }
    : {
        excludePunctuation: true,
        passwordLength: 40,
      };
  const secret = new secretsmanager.Secret(scope, id, {
    secretName: props.secretName,
    description: `${props.description} Dummy value — replace in Secrets Manager.`,
    encryptionKey: props.encryptionKey,
    removalPolicy: cdk.RemovalPolicy.RETAIN,
    generateSecretString: generator,
  });
  cdk.Tags.of(secret).add("lxsoftware:tenant", props.tenant);
  cdk.Tags.of(secret).add("lxsoftware:purpose", props.purpose);
  return secret;
}

/** Secrets Manager objects that already exist (failed-create leftovers). */
function boardImportedSecrets(
  scope: Construct,
  opts: {
    ids: {
      github: string;
      search: string;
      metaToken: string;
      metaAppSecret: string;
      appStore: string;
      play: string;
      analytics: string;
    };
    names: {
      github: string;
      search: string;
      metaToken: string;
      metaAppSecret: string;
      appStore: string;
      play: string;
      analytics: string;
    };
  }
): BoardConnectorSecrets {
  return {
    github: secretsmanager.Secret.fromSecretNameV2(scope, opts.ids.github, opts.names.github),
    search: secretsmanager.Secret.fromSecretNameV2(scope, opts.ids.search, opts.names.search),
    metaToken: secretsmanager.Secret.fromSecretNameV2(scope, opts.ids.metaToken, opts.names.metaToken),
    metaAppSecret: secretsmanager.Secret.fromSecretNameV2(
      scope,
      opts.ids.metaAppSecret,
      opts.names.metaAppSecret
    ),
    appStore: secretsmanager.Secret.fromSecretNameV2(scope, opts.ids.appStore, opts.names.appStore),
    play: secretsmanager.Secret.fromSecretNameV2(scope, opts.ids.play, opts.names.play),
    analytics: secretsmanager.Secret.fromSecretNameV2(scope, opts.ids.analytics, opts.names.analytics),
  };
}

function boardConnectorSecrets(
  scope: Construct,
  encryptionKey: kms.IKey,
  opts: {
    tenant: string;
    purpose: string;
    label: string;
    ids: {
      github: string;
      search: string;
      metaToken: string;
      metaAppSecret: string;
      appStore: string;
      play: string;
      analytics: string;
    };
    names: {
      github: string;
      search: string;
      metaToken: string;
      metaAppSecret: string;
      appStore: string;
      play: string;
      analytics: string;
    };
  }
): BoardConnectorSecrets {
  const common = {
    encryptionKey,
    tenant: opts.tenant,
    purpose: opts.purpose,
  };
  return {
    github: boardPlaceholderSecret(scope, opts.ids.github, {
      ...common,
      secretName: opts.names.github,
      description: `${opts.label}: fine-grained GitHub PAT (Contents read, Issues r/w, Actions read, Metadata read, Security events read).`,
    }),
    search: boardPlaceholderSecret(scope, opts.ids.search, {
      ...common,
      secretName: opts.names.search,
      description: `${opts.label}: Brave Search API key for research.`,
    }),
    metaToken: boardPlaceholderSecret(scope, opts.ids.metaToken, {
      ...common,
      secretName: opts.names.metaToken,
      description: `${opts.label}: Meta System User long-lived token (Page / Instagram / WhatsApp / ads).`,
    }),
    metaAppSecret: boardPlaceholderSecret(scope, opts.ids.metaAppSecret, {
      ...common,
      secretName: opts.names.metaAppSecret,
      description: `${opts.label}: Meta app secret for X-Hub-Signature-256 on POST /webhooks/meta/siutindei.`,
    }),
    appStore: boardPlaceholderSecret(scope, opts.ids.appStore, {
      ...common,
      secretName: opts.names.appStore,
      description: `${opts.label}: App Store Connect API key JSON (keyId, issuerId, privateKey, optional appId / vendorNumber).`,
      jsonTemplate: ASC_KEY_TEMPLATE,
      generateKey: "privateKey",
    }),
    play: boardPlaceholderSecret(scope, opts.ids.play, {
      ...common,
      secretName: opts.names.play,
      description: `${opts.label}: Google Play service-account JSON (client_email, private_key, optional packageName).`,
      jsonTemplate: PLAY_SA_TEMPLATE,
      generateKey: "private_key",
    }),
    analytics: boardPlaceholderSecret(scope, opts.ids.analytics, {
      ...common,
      secretName: opts.names.analytics,
      description: `${opts.label}: dedicated GA4 / GTM service-account JSON (not the Play key).`,
      jsonTemplate: ANALYTICS_SA_TEMPLATE,
      generateKey: "private_key",
    }),
  };
}

class SharedPermissionLambdaIntegration extends HttpLambdaIntegration {
  protected completeBind(_options: apigwv2.HttpRouteIntegrationBindOptions): void {
    // Intentionally empty: invoke permission is granted once for the whole API.
  }
}

/**
 * Consolidated admin backend stack: Cognito user pool (with Pre Token
 * Generation Lambda + Google IdP), DynamoDB tables, private uploads
 * bucket (with its own S3 access logs bucket), and the HTTP API plus
 * the admin Lambda that consumes them.
 *
 * All physical names use the `lxsoftware-admin-*` prefix.
 */
export class LxsoftwareStack extends cdk.Stack {
  public readonly auth: AuthConstruct;
  public readonly recordsTable: dynamodb.Table;
  public readonly auditLogTable: dynamodb.Table;
  public readonly assetsBucket: s3.Bucket;
  public readonly assetsAccessLogsBucket: s3.Bucket;
  public readonly httpApi: apigwv2.HttpApi;
  /**
   * Shared customer-managed KMS key used to encrypt:
   * - Lambda environment variables (Checkov CKV_AWS_173)
   * - CloudWatch log groups (Checkov CKV_AWS_158)
   * - DynamoDB tables (Checkov CKV_AWS_119)
   *
   * Cost: $1/month flat. KMS API calls for this workload (admin-only,
   * low-traffic) stay well under the 20,000/month free tier. Key
   * rotation is enabled (annual, AWS-managed).
   */
  public readonly sharedEncryptionKey: kms.Key;
  /**
   * Shared SQS dead-letter queue for failed async Lambda invocations
   * (Checkov CKV_AWS_116). One queue is used for every application
   * Lambda in the stack — sharing avoids per-function queue overhead and
   * stays within the SQS free tier (1M requests/month) for our admin
   * workload. Encrypted with the same shared CMK.
   */
  public readonly lambdaDeadLetterQueue: sqs.Queue;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ------------------------------------------------------------------
    // CloudFormation parameters
    // ------------------------------------------------------------------
    const adminWebDomainName = new cdk.CfnParameter(this, "AdminWebDomainName", {
      type: "String",
      description: "Public hostname for the admin SPA (e.g. admin.lx-software.com).",
      default: ADMIN_WEB_HOSTNAME,
    });

    const googleClientId = new cdk.CfnParameter(this, "GoogleClientId", {
      type: "String",
      description: "Google OAuth client ID for Cognito federation.",
    });

    const googleClientSecret = new cdk.CfnParameter(this, "GoogleClientSecret", {
      type: "String",
      description: "Google OAuth client secret for Cognito federation.",
      noEcho: true,
    });

    const adminFederatedEmailAllowlist = new cdk.CfnParameter(
      this,
      "AdminFederatedEmailAllowlist",
      {
        type: "String",
        description:
          "Comma-separated lower-case emails that receive the admin group in tokens (Pre Token Generation). Include every Google admin and the bootstrap email.",
      }
    );

    const adminBootstrapEmail = new cdk.CfnParameter(this, "AdminBootstrapEmail", {
      type: "String",
      description: "Email for the initial native admin user (bootstrap).",
    });

    const adminBootstrapTempPassword = new cdk.CfnParameter(
      this,
      "AdminBootstrapTempPassword",
      {
        type: "String",
        description:
          "Temporary password for bootstrap admin (must meet pool policy; rotate after first login).",
        noEcho: true,
      }
    );

    const cognitoDomainPrefix = new cdk.CfnParameter(this, "CognitoDomainPrefix", {
      type: "String",
      description: "Globally unique Cognito hosted UI domain prefix.",
      default: "lxsoftware-admin-auth",
    });

    const cognitoCustomDomainName = new cdk.CfnParameter(
      this,
      "CognitoCustomDomainName",
      {
        type: "String",
        default: "",
        description:
          "Optional custom Hosted UI domain (e.g. auth.lx-software.com). " +
          "Set together with CognitoCustomDomainCertificateArn; leave empty for the prefix domain.",
      }
    );

    const cognitoCustomDomainCertificateArn = new cdk.CfnParameter(
      this,
      "CognitoCustomDomainCertificateArn",
      {
        type: "String",
        default: "",
        description:
          "ACM certificate ARN for the Cognito custom domain (must be in us-east-1).",
      }
    );

    const openRouterApiKeySecretArn = new cdk.CfnParameter(
      this,
      "OpenRouterApiKeySecretArn",
      {
        type: "String",
        default: "",
        description:
          "ARN of the AWS Secrets Manager secret holding the OpenRouter API key (used by the admin Lambda to parse uploaded statement PDFs). Leave blank to disable PDF statement parsing.",
      }
    );

    const openRouterModel = new cdk.CfnParameter(this, "OpenRouterModel", {
      type: "String",
      default: "mistralai/mistral-medium-3",
      description:
        "OpenRouter model slug used when extracting statement lines from uploaded PDFs.",
    });

    const openRouterPdfEngine = new cdk.CfnParameter(this, "OpenRouterPdfEngine", {
      type: "String",
      default: "mistral-ocr",
      description:
        "OpenRouter file-parser PDF engine: pdf-text (free, text-based PDFs), mistral-ocr (paid, scanned PDFs), or native (model-native parsing).",
    });

    const enableBankingAppId = new cdk.CfnParameter(this, "EnableBankingAppId", {
      type: "String",
      default: "",
      description:
        "Enable Banking application id (JWT kid) for the bank account sync. " +
        "Register the app at enablebanking.com with the public key of the " +
        "EnableBankingSigningKey KMS key (scripts/export-enable-banking-public-key.py). " +
        "Leave blank to disable bank sync.",
    });

    // Executive Board (AI board for Siu Tin Dei; see docs/architecture/executive-board-plan.md)
    const siutindeiClusterArn = new cdk.CfnParameter(
      this,
      "SiutindeiClusterArn",
      {
        type: "String",
        default: "",
        description:
          "Aurora cluster ARN for the siutindei database (RDS Data API). Required for Executive Board finance and product tools.",
      }
    );
    const siutindeiDbSecretArn = new cdk.CfnParameter(
      this,
      "SiutindeiDbSecretArn",
      {
        type: "String",
        default: "",
        description:
          "Secrets Manager ARN of the siutindei DB credentials used by the RDS Data API.",
      }
    );
    const metaVerifyToken = new cdk.CfnParameter(this, "MetaVerifyToken", {
      type: "String",
      default: "",
      noEcho: true,
      description:
        "Verify token Meta sends on GET /webhooks/meta/siutindei (hub.verify_token). Leave blank to keep the handshake rejected.",
    });
    const metaPageId = new cdk.CfnParameter(this, "MetaPageId", {
      type: "String",
      default: "",
      description: "Facebook Page id for Executive Board meta tools.",
    });
    const metaIgUserId = new cdk.CfnParameter(this, "MetaIgUserId", {
      type: "String",
      default: "",
      description: "Instagram professional-account id for Executive Board meta tools.",
    });
    const metaWaPhoneNumberId = new cdk.CfnParameter(
      this,
      "MetaWaPhoneNumberId",
      {
        type: "String",
        default: "",
        description:
          "WhatsApp Cloud API phone-number id. Enable coexistence so the owner's phone keeps working.",
      }
    );
    const metaAdAccountId = new cdk.CfnParameter(this, "MetaAdAccountId", {
      type: "String",
      default: "",
      description: "Meta ad account id (with or without act_ prefix).",
    });
    const metaWabaId = new cdk.CfnParameter(this, "MetaWabaId", {
      type: "String",
      default: "",
      description:
        "WhatsApp Business Account id for listing message templates. Optional if the phone-number id can resolve it.",
    });
    const appStoreConnectAppId = new cdk.CfnParameter(
      this,
      "AppStoreConnectAppId",
      {
        type: "String",
        default: "",
        description:
          "App Store Connect app id (numeric). May also live inside the AppStoreConnectKey secret.",
      }
    );
    const appStoreConnectVendorNumber = new cdk.CfnParameter(
      this,
      "AppStoreConnectVendorNumber",
      {
        type: "String",
        default: "",
        description:
          "App Store Connect vendor number used to download daily sales reports (stores_metrics downloads). May also live inside the AppStoreConnectKey secret as vendorNumber.",
      }
    );
    const googlePlayPackageName = new cdk.CfnParameter(
      this,
      "GooglePlayPackageName",
      {
        type: "String",
        default: "",
        description:
          "Google Play package name (e.g. com.siutindei.app). May also live inside the service-account secret.",
      }
    );
    const ga4PropertyIds = new cdk.CfnParameter(this, "Ga4PropertyIds", {
      type: "String",
      default: "",
      description:
        "Comma-separated GA4 property ids (numeric, with or without a properties/ prefix). Several properties are supported.",
    });
    const gtmContainers = new cdk.CfnParameter(this, "GtmContainers", {
      type: "String",
      default: "",
      description:
        "Comma-separated GTM account:container pairs (e.g. 123:456,123:789). Used for web_gtm_status.",
    });
    const boardAwsStackPrefix = new cdk.CfnParameter(
      this,
      "BoardAwsStackPrefix",
      {
        type: "String",
        default: "siutindei",
        description:
          "CloudFormation stack-name prefix used to filter Cost Explorer and CloudWatch results for the Executive Board aws tool.",
      }
    );
    const boardAwsLambdaNames = new cdk.CfnParameter(
      this,
      "BoardAwsLambdaNames",
      {
        type: "String",
        default: "",
        description:
          "Comma-separated Lambda function names (siutindei stack) whose 24h errors/duration the Executive Board aws_lambda_health tool reports. Empty disables the read.",
      }
    );
    const boardToolsEnabled = new cdk.CfnParameter(this, "BoardToolsEnabled", {
      type: "String",
      default: "true",
      allowedValues: ["true", "false"],
      description:
        "Kill switch for Executive Board tool calls (GitHub, board, mail, research, AWS, security). Set to false to stop every tool call without touching the admin settings.",
    });
    const boardStaffEnabled = new cdk.CfnParameter(this, "BoardStaffEnabled", {
      type: "String",
      default: "false",
      allowedValues: ["true", "false"],
      description:
        "Kill switch for Executive Board staff tasks. Default false until the task engine and daily review are live. Also requires settings.staff.enabled.",
    });
    const outreachSendingDomain = new cdk.CfnParameter(this, "OutreachSendingDomain", {
      type: "String",
      default: "partners.siutindei.com",
      description:
        "SES From domain for Executive Board cold outreach. Owner must add DKIM CNAMEs, MAIL FROM MX+TXT and DMARC before sending succeeds.",
    });
    const outreachFromLocalPart = new cdk.CfnParameter(this, "OutreachFromLocalPart", {
      type: "String",
      default: "partnerships",
      description: "Local part of the outreach From address (partnerships@OutreachSendingDomain).",
    });
    const publicApiBaseUrl = new cdk.CfnParameter(this, "PublicApiBaseUrl", {
      type: "String",
      default: "",
      description:
        "Public base URL for unsubscribe and newsletter confirm links. Leave blank to use this stack's HTTP API URL.",
    });
    const boardGitHubRepo = new cdk.CfnParameter(this, "BoardGitHubRepo", {
      type: "String",
      default: "lx-software-ltd/siutindei",
      description: "owner/name of the repository the Executive Board reads.",
    });
    const boardMailDomain = new cdk.CfnParameter(this, "BoardMailDomain", {
      type: "String",
      default: "siutindei.com",
      description:
        "Company mail domain the Executive Board reads. Every message to any mailbox at this domain is fanned out by a Cloudflare Email Worker to the board's SES inbound address and indexed (docs/architecture/executive-board-tools-plan.md §5.2).",
    });
    const boardMailSendingEnabled = new cdk.CfnParameter(
      this,
      "BoardMailSendingEnabled",
      {
        type: "String",
        default: "false",
        allowedValues: ["true", "false"],
        description:
          "Set to true once BoardMailDomain is verified for sending in SES (DKIM CNAMEs, SPF include:amazonses.com, DMARC). Creates the SES identity and lets the board's mail tools send replies from that domain; false keeps mail read-only.",
      }
    );
    const boardChatModel = new cdk.CfnParameter(this, "BoardChatModel", {
      type: "String",
      default: "openai/gpt-4.1-mini",
      description: "OpenRouter model slug for Executive Board chats (overridable in the admin settings).",
    });
    const boardMeetingModel = new cdk.CfnParameter(this, "BoardMeetingModel", {
      type: "String",
      default: "openai/gpt-4.1-mini",
      description: "OpenRouter model slug for Executive Board stand-up meetings.",
    });
    const boardDeepDiveModel = new cdk.CfnParameter(this, "BoardDeepDiveModel", {
      type: "String",
      default: "anthropic/claude-sonnet-4",
      description: "OpenRouter model slug for Executive Board deep-dive meetings.",
    });

    // ------------------------------------------------------------------
    // 1. Shared KMS encryption key + Lambda DLQ
    //
    // One customer-managed key fans out to Lambda env vars, CloudWatch
    // log groups, DynamoDB tables, and the shared SQS DLQ. This keeps
    // the recurring KMS bill at $1/month total (vs. ~$7/month if every
    // resource minted its own key) while still satisfying Checkov
    // CKV_AWS_158 / 173 / 119.
    //
    // The key policy below grants the CloudWatch Logs service principal
    // the Encrypt/Decrypt actions it needs to write encrypted log events,
    // scoped via `kms:EncryptionContext:aws:logs:arn` to log groups in
    // this account/region only.
    // ------------------------------------------------------------------
    this.sharedEncryptionKey = new kms.Key(this, "SharedEncryptionKey", {
      alias: "lxsoftware-admin/shared",
      description:
        "Shared CMK for Lambda env vars, CloudWatch logs, DynamoDB, and SQS DLQ in the lxsoftware admin stack.",
      enableKeyRotation: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const region = cdk.Stack.of(this).region;
    const accountId = cdk.Stack.of(this).account;
    this.sharedEncryptionKey.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "AllowCloudWatchLogsEncryption",
        principals: [
          new iam.ServicePrincipal(`logs.${region}.amazonaws.com`),
        ],
        actions: [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:Describe*",
        ],
        resources: ["*"],
        conditions: {
          ArnLike: {
            "kms:EncryptionContext:aws:logs:arn": `arn:aws:logs:${region}:${accountId}:*`,
          },
        },
      })
    );

    this.lambdaDeadLetterQueue = new sqs.Queue(this, "LambdaDeadLetterQueue", {
      queueName: "lxsoftware-admin-lambda-dlq",
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: this.sharedEncryptionKey,
      retentionPeriod: cdk.Duration.days(14),
    });

    // ------------------------------------------------------------------
    // 2. Auth (Cognito user pool, Google IdP, hosted UI, bootstrap admin)
    // ------------------------------------------------------------------
    this.auth = new AuthConstruct(this, "Auth", {
      adminWebDomainParameter: adminWebDomainName,
      googleClientIdParameter: googleClientId,
      googleClientSecretParameter: googleClientSecret,
      cognitoDomainPrefixParameter: cognitoDomainPrefix,
      cognitoCustomDomainNameParameter: cognitoCustomDomainName,
      cognitoCustomDomainCertificateArnParameter: cognitoCustomDomainCertificateArn,
      adminBootstrapEmailParameter: adminBootstrapEmail,
      adminBootstrapTempPasswordParameter: adminBootstrapTempPassword,
      adminFederatedEmailAllowlistParameter: adminFederatedEmailAllowlist,
      sharedEncryptionKey: this.sharedEncryptionKey,
      sharedDeadLetterQueue: this.lambdaDeadLetterQueue,
    });

    // ------------------------------------------------------------------
    // 3. Data (DynamoDB tables)
    //
    // Both tables use the shared customer-managed KMS key (CKV_AWS_119).
    // KMS API calls are charged per request beyond the free tier (20k/mo),
    // but the admin-only workload stays well below that ceiling.
    // ------------------------------------------------------------------
    this.recordsTable = new dynamodb.Table(this, "RecordsTable", {
      tableName: "lxsoftware-admin-records",
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: this.sharedEncryptionKey,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    this.recordsTable.addGlobalSecondaryIndex({
      indexName: "gsi1",
      partitionKey: { name: "gsi1pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "gsi1sk", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    const recordsTableCfn = this.recordsTable.node.defaultChild as dynamodb.CfnTable;
    recordsTableCfn.timeToLiveSpecification = {
      attributeName: "expiresAt",
      enabled: true,
    };

    this.auditLogTable = new dynamodb.Table(this, "AuditLogTable", {
      tableName: "lxsoftware-admin-audit-log",
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: this.sharedEncryptionKey,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ------------------------------------------------------------------
    // 3. Assets (private uploads bucket + S3 access logs bucket)
    //
    // Bucket-name length budget: S3 caps the name at 63 chars. With a
    // 12-digit account ID and the longest current AWS region label
    // (`ap-southeast-1`, 14 chars) the suffix is `-{12}-{14}` = 28 chars,
    // leaving 35 chars for the prefix. Both names below stay within that
    // budget; `assets-logs` is the deliberately shortened form of the
    // legacy `assets-s3-access-logs` (which would now exceed 63 chars).
    // ------------------------------------------------------------------
    const assetsBucketName = [
      "lxsoftware-admin-assets",
      cdk.Aws.ACCOUNT_ID,
      cdk.Aws.REGION,
    ].join("-");

    const assetsAccessLogsBucketName = [
      "lxsoftware-admin-assets-logs",
      cdk.Aws.ACCOUNT_ID,
      cdk.Aws.REGION,
    ].join("-");

    this.assetsAccessLogsBucket = new s3.Bucket(this, "AssetsS3AccessLogsBucket", {
      bucketName: assetsAccessLogsBucketName,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          id: "ExpireOldS3AccessLogs",
          enabled: true,
          expiration: cdk.Duration.days(90),
        },
      ],
    });

    /**
     * Private uploads bucket: BlockPublicAccess does not disable CORS — browsers
     * still send Origin on PUT/POST to S3; CORS is evaluated for authenticated
     * requests including presigned POST/PUT.
     */
    this.assetsBucket = new s3.Bucket(this, "AssetsBucket", {
      bucketName: assetsBucketName,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      serverAccessLogsBucket: this.assetsAccessLogsBucket,
      serverAccessLogsPrefix: "assets-data-bucket/",
      cors: [
        {
          allowedMethods: [
            s3.HttpMethods.PUT,
            s3.HttpMethods.POST,
            s3.HttpMethods.GET,
          ],
          allowedOrigins: [
            cdk.Fn.join("", ["https://", adminWebDomainName.valueAsString]),
          ],
          allowedHeaders: ["*"],
          maxAge: 3000,
        },
      ],
      lifecycleRules: [
        {
          id: "AbortIncompleteMultipartUploads",
          enabled: true,
          abortIncompleteMultipartUploadAfter: cdk.Duration.days(7),
        },
        {
          id: "GlacierInstantRetrievalForNonCurrentVersions",
          enabled: true,
          noncurrentVersionTransitions: [
            {
              storageClass: s3.StorageClass.GLACIER_INSTANT_RETRIEVAL,
              transitionAfter: cdk.Duration.days(30),
            },
          ],
        },
      ],
    });

    // ------------------------------------------------------------------
    // 4. HTTP API + admin Lambda
    // ------------------------------------------------------------------
    const issuer = `https://cognito-idp.${region}.amazonaws.com/${this.auth.userPool.userPoolId}`;

    /**
     * Contract: jwtAudience is the Cognito app client ID, which matches the
     * `aud` claim on **ID tokens** only. Access tokens use `client_id` instead
     * of `aud`, so the SPA must send ID tokens in Authorization (see
     * apps/admin_web/src/lib/apiAdminClient.ts). Switching to access tokens
     * requires a different authorizer configuration.
     */
    const jwtAuthorizer = new HttpJwtAuthorizer("cognito-jwt", issuer, {
      jwtAudience: [this.auth.userPoolClient.userPoolClientId],
    });

    /**
     * Public read-only API key authorizer. Validates the `x-api-key` header
     * against scrypt key digests stored in the records table
     * (`pk = APIKEY#<digest>`, `sk = META`; minted via
     * scripts/manage-public-api-keys.py). Guards only the /public/* GET
     * routes below — every write route stays on the Cognito JWT authorizer,
     * so a leaked key can never mutate state even if the handler-level
     * allowlist regressed.
     */
    const publicApiKeyAuthorizerFn = createPythonLambda(
      this,
      "PublicApiKeyAuthorizerFn",
      {
        entryDir: path.join(__dirname, "..", "..", "lambda", "public_api_authorizer"),
        timeout: cdk.Duration.seconds(5),
        memorySize: 256,
        environmentEncryptionKey: this.sharedEncryptionKey,
        logEncryptionKey: this.sharedEncryptionKey,
        deadLetterQueue: this.lambdaDeadLetterQueue,
        environment: {
          RECORDS_TABLE_NAME: this.recordsTable.tableName,
        },
      }
    );
    this.lambdaDeadLetterQueue.grantSendMessages(publicApiKeyAuthorizerFn);

    // Narrow read grant: the authorizer can only GetItem on APIKEY#* rows,
    // never finance/asset records. The table uses the shared CMK, so a
    // matching kms:Decrypt grant is required for reads to succeed.
    new iam.Policy(this, "PublicApiKeyAuthorizerReadPolicy", {
      statements: [
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["dynamodb:GetItem"],
          resources: [this.recordsTable.tableArn],
          conditions: {
            "ForAllValues:StringLike": {
              "dynamodb:LeadingKeys": ["APIKEY#*"],
            },
          },
        }),
      ],
    }).attachToRole(publicApiKeyAuthorizerFn.role!);
    this.sharedEncryptionKey.grantDecrypt(publicApiKeyAuthorizerFn);

    const publicApiKeyAuthorizer = new HttpLambdaAuthorizer(
      "public-api-key",
      publicApiKeyAuthorizerFn,
      {
        responseTypes: [HttpLambdaResponseType.SIMPLE],
        identitySource: ["$request.header.x-api-key"],
        // Cache authorizer verdicts per key so the DynamoDB lookup (and its
        // KMS decrypt) does not run on every request. Revocation therefore
        // takes up to this TTL to propagate.
        resultsCacheTtl: cdk.Duration.minutes(5),
      }
    );

    /**
     * Statement PDF parsing runs on async self-invoke of AdminApiFn (HTTP API
     * stays sub-30s). Keep Lambda timeout, OpenRouter urllib timeout, job stale/
     * stuck thresholds, and the admin SPA poll deadline (`useParseStatement.ts`)
     * in a consistent order: OpenRouter + cold-start headroom < Lambda ≤ stale
     * ≤ stuck < browser poll < async maxEventAge.
     */
    const adminStatementParseLambdaTimeout = cdk.Duration.seconds(
      PARSE_TIMEOUTS.lambdaTimeoutSeconds
    );
    const openRouterHttpTimeoutSeconds = String(
      PARSE_TIMEOUTS.openRouterTimeoutSeconds
    );
    const parseJobStaleSeconds = String(PARSE_TIMEOUTS.parseJobStaleSeconds);
    const parseJobStuckSeconds = String(PARSE_TIMEOUTS.parseJobStuckSeconds);

    /**
     * Already-deployed connector secrets. Construct ids must stay so
     * CloudFormation does not replace them. Reserved for a future LX
     * Software Executive Board — AdminApiFn does not read these today.
     */
    boardConnectorSecrets(this, this.sharedEncryptionKey, {
      tenant: "lxsoftware",
      purpose: "lxsoftware-executive-board",
      label: "Reserved for a future LX Software Executive Board",
      ids: {
        github: "BoardGitHubReadToken",
        search: "BoardSearchApiKey",
        metaToken: "BoardMetaToken",
        metaAppSecret: "BoardMetaAppSecret",
        appStore: "BoardAppStoreConnectKey",
        play: "BoardGooglePlaySa",
        analytics: "BoardGoogleAnalyticsSa",
      },
      names: {
        github: "lxsoftware-admin-github-read-token",
        search: "lxsoftware-admin-search-api-key",
        metaToken: "lxsoftware-admin-meta-board-token",
        metaAppSecret: "lxsoftware-admin-meta-app-secret",
        appStore: "lxsoftware-admin-app-store-connect-key",
        play: "lxsoftware-admin-google-play-sa",
        analytics: "lxsoftware-admin-google-analytics-sa",
      },
    });

    /**
     * Siu Tin Dei Executive Board — what AdminApiFn uses. These named
     * secrets already exist in the account (CREATE succeeded, then
     * RemovalPolicy.RETAIN skipped delete on rollback). Import by name so
     * CloudFormation does not try to create them again.
     */
    const siutindeiBoardSecrets = boardImportedSecrets(this, {
      ids: {
        github: "SiutindeiBoardGitHubToken",
        search: "SiutindeiBoardSearchApiKey",
        metaToken: "SiutindeiBoardMetaToken",
        metaAppSecret: "SiutindeiBoardMetaAppSecret",
        appStore: "SiutindeiBoardAppStoreConnectKey",
        play: "SiutindeiBoardGooglePlaySa",
        analytics: "SiutindeiBoardGoogleAnalyticsSa",
      },
      names: {
        github: "lxsoftware-admin-siutindei-board-github-token",
        search: "lxsoftware-admin-siutindei-board-search-api-key",
        metaToken: "lxsoftware-admin-siutindei-board-meta-token",
        metaAppSecret: "lxsoftware-admin-siutindei-board-meta-app-secret",
        appStore: "lxsoftware-admin-siutindei-board-app-store-connect-key",
        play: "lxsoftware-admin-siutindei-board-google-play-sa",
        analytics: "lxsoftware-admin-siutindei-board-google-analytics-sa",
      },
    });
    const googlePlacesKeySecret = boardPlaceholderSecret(this, "SiutindeiBoardGooglePlacesKey", {
      secretName: "lxsoftware-admin-siutindei-board-google-places-key",
      description: "Siu Tin Dei Executive Board: Google Places API (New) key, restricted to Places.",
      encryptionKey: this.sharedEncryptionKey,
      tenant: "siutindei",
      purpose: "board-places",
    });
    const boardLinkSigningSecret = boardPlaceholderSecret(this, "SiutindeiBoardLinkSigningKey", {
      secretName: "lxsoftware-admin-siutindei-board-link-signing-key",
      description: "Siu Tin Dei Executive Board: HMAC key for outreach unsubscribe and newsletter confirm tokens.",
      encryptionKey: this.sharedEncryptionKey,
      tenant: "siutindei",
      purpose: "board-link-signing",
    });

    /**
     * Asymmetric RSA key that signs the Enable Banking RS256 JWTs. The
     * private key never leaves KMS; the admin Lambda calls kms:Sign per
     * token (tokens are cached for ~1h in the Lambda, so call volume is
     * negligible). RETAIN: losing the key would orphan the Enable Banking
     * application registration. Asymmetric KMS keys do not support
     * automatic rotation.
     */
    const enableBankingSigningKey = new kms.Key(this, "EnableBankingSigningKey", {
      alias: "lxsoftware-admin/enable-banking",
      description:
        "RSA signing key for Enable Banking API JWTs (bank account sync).",
      keySpec: kms.KeySpec.RSA_2048,
      keyUsage: kms.KeyUsage.SIGN_VERIFY,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const adminFn = createPythonLambda(this, "AdminApiFn", {
      entryDir: path.join(__dirname, "..", "..", "lambda", "admin"),
      timeout: adminStatementParseLambdaTimeout,
      memorySize: 1536,
      environmentEncryptionKey: this.sharedEncryptionKey,
      logEncryptionKey: this.sharedEncryptionKey,
      deadLetterQueue: this.lambdaDeadLetterQueue,
      environment: {
        RECORDS_TABLE_NAME: this.recordsTable.tableName,
        AUDIT_LOG_TABLE_NAME: this.auditLogTable.tableName,
        ASSETS_BUCKET_NAME: this.assetsBucket.bucketName,
        ASSET_MAX_BYTES: String(20 * 1024 * 1024),
        OPENROUTER_API_KEY_SECRET_ARN: openRouterApiKeySecretArn.valueAsString,
        OPENROUTER_MODEL: openRouterModel.valueAsString,
        OPENROUTER_PDF_ENGINE: openRouterPdfEngine.valueAsString,
        OPENROUTER_TIMEOUT_SECONDS: openRouterHttpTimeoutSeconds,
        PARSE_JOB_STALE_SECONDS: parseJobStaleSeconds,
        PARSE_JOB_STUCK_SECONDS: parseJobStuckSeconds,
        PARSE_JOB_TTL_SECONDS: String(PARSE_TIMEOUTS.parseJobTtlSeconds),
        ENABLE_BANKING_APP_ID: enableBankingAppId.valueAsString,
        ENABLE_BANKING_KMS_KEY_ID: enableBankingSigningKey.keyId,
        GITHUB_READ_TOKEN_SECRET_ARN: siutindeiBoardSecrets.github.secretArn,
        BOARD_GITHUB_REPO: boardGitHubRepo.valueAsString,
        BOARD_CHAT_MODEL: boardChatModel.valueAsString,
        BOARD_MEETING_MODEL: boardMeetingModel.valueAsString,
        BOARD_DEEP_DIVE_MODEL: boardDeepDiveModel.valueAsString,
        BOARD_TOOLS_ENABLED: boardToolsEnabled.valueAsString,
        BOARD_STAFF_ENABLED: boardStaffEnabled.valueAsString,
        OUTREACH_SENDING_DOMAIN: outreachSendingDomain.valueAsString,
        OUTREACH_FROM_LOCAL_PART: outreachFromLocalPart.valueAsString,
        NEWSLETTER_CONFIG_SET: "lxsoftware-admin-siutindei-newsletter",
        NEWSLETTER_FROM_LOCAL_PART: "news",
        SEARCH_API_KEY_SECRET_ARN: siutindeiBoardSecrets.search.secretArn,
        BOARD_AWS_STACK_PREFIX: boardAwsStackPrefix.valueAsString,
        BOARD_AWS_LAMBDA_NAMES: boardAwsLambdaNames.valueAsString,
        USER_POOL_ID: this.auth.userPool.userPoolId,
        SIUTINDEI_CLUSTER_ARN: siutindeiClusterArn.valueAsString,
        SIUTINDEI_DB_SECRET_ARN: siutindeiDbSecretArn.valueAsString,
        META_BOARD_TOKEN_SECRET_ARN: siutindeiBoardSecrets.metaToken.secretArn,
        META_APP_SECRET_SECRET_ARN: siutindeiBoardSecrets.metaAppSecret.secretArn,
        META_VERIFY_TOKEN: metaVerifyToken.valueAsString,
        META_PAGE_ID: metaPageId.valueAsString,
        META_IG_USER_ID: metaIgUserId.valueAsString,
        META_WA_PHONE_NUMBER_ID: metaWaPhoneNumberId.valueAsString,
        META_WABA_ID: metaWabaId.valueAsString,
        META_AD_ACCOUNT_ID: metaAdAccountId.valueAsString,
        APP_STORE_CONNECT_KEY_SECRET_ARN: siutindeiBoardSecrets.appStore.secretArn,
        GOOGLE_PLAY_SERVICE_ACCOUNT_SECRET_ARN: siutindeiBoardSecrets.play.secretArn,
        APP_STORE_CONNECT_APP_ID: appStoreConnectAppId.valueAsString,
        ASC_VENDOR_NUMBER: appStoreConnectVendorNumber.valueAsString,
        GOOGLE_PLAY_PACKAGE_NAME: googlePlayPackageName.valueAsString,
        GOOGLE_ANALYTICS_SERVICE_ACCOUNT_SECRET_ARN: siutindeiBoardSecrets.analytics.secretArn,
        GOOGLE_PLACES_KEY_SECRET_ARN: googlePlacesKeySecret.secretArn,
        BOARD_LINK_SIGNING_SECRET_ARN: boardLinkSigningSecret.secretArn,
        GA4_PROPERTY_IDS: ga4PropertyIds.valueAsString,
        GTM_CONTAINERS: gtmContainers.valueAsString,
        // BOARD_MAIL_DOMAIN / _RAW_SEGMENT / _INBOUND_ADDRESS are added with the
        // inbound-mail resources below (they depend on InboundMailDomain).
        BOARD_MAIL_SENDING_ENABLED: boardMailSendingEnabled.valueAsString,
        ADMIN_WEB_ORIGIN: cdk.Fn.join("", [
          "https://",
          adminWebDomainName.valueAsString,
        ]),
      },
    });

    enableBankingSigningKey.grant(adminFn, "kms:Sign", "kms:GetPublicKey");

    // Siu Tin Dei Executive Board schedules. Explicit scheduleName + boardKey
    // so a later LX Software board can add a parallel set without colliding.
    // EventBridge Scheduler (not an events.Rule): invokes through an IAM role
    // so we do not add more Lambda resource-policy statements (20 KB cap).
    const siutindeiBoardKey = "siuTinDei";
    const siutindeiBoardSchedule = (
      id: string,
      scheduleName: string,
      description: string,
      schedule: scheduler.ScheduleExpression,
      input: Record<string, string>,
      retryAttempts: number
    ) =>
      new scheduler.Schedule(this, id, {
        scheduleName,
        description,
        schedule,
        target: new schedulerTargets.LambdaInvoke(adminFn, {
          input: scheduler.ScheduleTargetInput.fromObject({
            ...input,
            boardKey: siutindeiBoardKey,
          }),
          retryAttempts,
        }),
      });
    const siutindeiStandup = (id: string, name: string, slot: "morning" | "evening", hour: string) =>
      siutindeiBoardSchedule(
        id,
        name,
        `Siu Tin Dei Executive Board ${slot} stand-up (${hour.padStart(2, "0")}:00 HKT) when enabled in settings.`,
        scheduler.ScheduleExpression.cron({
          minute: "0",
          hour,
          timeZone: cdk.TimeZone.ASIA_HONG_KONG,
        }),
        { internal: "board_meeting", trigger: "schedule", slot },
        0
      );
    siutindeiStandup(
      "SiutindeiBoardMorningMeetingSchedule",
      "lxsoftware-admin-siutindei-board-standup-morning",
      "morning",
      "6"
    );
    siutindeiStandup(
      "SiutindeiBoardEveningMeetingSchedule",
      "lxsoftware-admin-siutindei-board-standup-evening",
      "evening",
      "18"
    );
    siutindeiBoardSchedule(
      "SiutindeiBoardReceivablesMirrorSchedule",
      "lxsoftware-admin-siutindei-board-receivables-mirror",
      "Nightly mirror of siutindei invoices/payments into the Siu Tin Dei statement book (HKT 00:30).",
      scheduler.ScheduleExpression.cron({
        minute: "30",
        hour: "0",
        timeZone: cdk.TimeZone.ASIA_HONG_KONG,
      }),
      { internal: "board_receivables_mirror" },
      1
    );
    siutindeiBoardSchedule(
      "SiutindeiBoardDunningSchedule",
      "lxsoftware-admin-siutindei-board-dunning",
      "Daily 09:00 HKT dunning: queues propose-level invoice reminders at D+7 / D+21 / D+35.",
      scheduler.ScheduleExpression.cron({
        minute: "0",
        hour: "9",
        timeZone: cdk.TimeZone.ASIA_HONG_KONG,
      }),
      { internal: "board_dunning" },
      0
    );
    siutindeiBoardSchedule(
      "SiutindeiBoardCacheRefreshSchedule",
      "lxsoftware-admin-siutindei-board-cache-refresh",
      "Hourly refresh of Siu Tin Dei Executive Board AWS / security / stores / web cache (HKT).",
      scheduler.ScheduleExpression.rate(cdk.Duration.hours(1)),
      { internal: "board_cache_refresh" },
      1
    );
    siutindeiBoardSchedule(
      "SiutindeiBoardStaffTickSchedule",
      "lxsoftware-admin-siutindei-board-staff-tick",
      "Every 5 minutes: drain the staff task queue and sweep stuck tasks.",
      scheduler.ScheduleExpression.rate(cdk.Duration.minutes(5)),
      { internal: "board_staff_tick" },
      0
    );
    siutindeiBoardSchedule(
      "SiutindeiBoardReviewCompileSchedule",
      "lxsoftware-admin-siutindei-board-review-compile",
      "Daily 07:15 HKT compile of the Executive Board review snapshot.",
      scheduler.ScheduleExpression.cron({
        minute: "15",
        hour: "7",
        timeZone: cdk.TimeZone.ASIA_HONG_KONG,
      }),
      { internal: "board_review_compile" },
      0
    );
    siutindeiBoardSchedule(
      "SiutindeiBoardReviewSendSchedule",
      "lxsoftware-admin-siutindei-board-review-send",
      "Daily 07:30 HKT digest email of the Executive Board review.",
      scheduler.ScheduleExpression.cron({
        minute: "30",
        hour: "7",
        timeZone: cdk.TimeZone.ASIA_HONG_KONG,
      }),
      { internal: "board_review_send" },
      0
    );
    siutindeiBoardSchedule(
      "SiutindeiBoardIntelCrawlSchedule",
      "lxsoftware-admin-siutindei-board-intel-crawl",
      "Daily 03:00 HKT crawl of the Executive Board competitor watchlist.",
      scheduler.ScheduleExpression.cron({
        minute: "0",
        hour: "3",
        timeZone: cdk.TimeZone.ASIA_HONG_KONG,
      }),
      { internal: "board_intel_crawl" },
      0
    );
    siutindeiBoardSchedule(
      "SiutindeiBoardIntelWeeklySchedule",
      "lxsoftware-admin-siutindei-board-intel-weekly",
      "Monday 04:00 HKT watchlist discovery and weekly market brief.",
      scheduler.ScheduleExpression.cron({
        minute: "0",
        hour: "4",
        weekDay: "MON",
        timeZone: cdk.TimeZone.ASIA_HONG_KONG,
      }),
      { internal: "board_intel_weekly" },
      0
    );
    siutindeiBoardSchedule(
      "SiutindeiBoardTargetsSchedule",
      "lxsoftware-admin-siutindei-board-targets",
      "Daily 08:00 HKT pipeline target check: qualify shortfall, due touches, cap raise.",
      scheduler.ScheduleExpression.cron({
        minute: "0",
        hour: "8",
        timeZone: cdk.TimeZone.ASIA_HONG_KONG,
      }),
      { internal: "board_targets" },
      0
    );
    siutindeiBoardSchedule(
      "SiutindeiBoardContentPlanSchedule",
      "lxsoftware-admin-siutindei-board-content-plan",
      "Sunday 18:00 HKT content calendar planning duty.",
      scheduler.ScheduleExpression.cron({
        minute: "0",
        hour: "18",
        weekDay: "SUN",
        timeZone: cdk.TimeZone.ASIA_HONG_KONG,
      }),
      { internal: "board_content_plan" },
      0
    );
    siutindeiBoardSchedule(
      "SiutindeiBoardContentReadoutSchedule",
      "lxsoftware-admin-siutindei-board-content-readout",
      "Monday 09:00 HKT weekly content performance readout.",
      scheduler.ScheduleExpression.cron({
        minute: "0",
        hour: "9",
        weekDay: "MON",
        timeZone: cdk.TimeZone.ASIA_HONG_KONG,
      }),
      { internal: "board_content_readout" },
      0
    );

    const outreachEventsDlq = new sqs.Queue(this, "SiutindeiOutreachEventsDlq", {
      queueName: "lxsoftware-admin-siutindei-outreach-events-dlq",
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: this.sharedEncryptionKey,
      retentionPeriod: cdk.Duration.days(14),
    });
    const outreachEventsQueue = new sqs.Queue(this, "SiutindeiOutreachEventsQueue", {
      queueName: "lxsoftware-admin-siutindei-outreach-events",
      visibilityTimeout: cdk.Duration.seconds(60),
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: this.sharedEncryptionKey,
      deadLetterQueue: { queue: outreachEventsDlq, maxReceiveCount: 5 },
    });
    const outreachEventsTopic = new sns.Topic(this, "SiutindeiOutreachEventsTopic", {
      topicName: "lxsoftware-admin-siutindei-outreach-events",
      masterKey: this.sharedEncryptionKey,
    });
    outreachEventsTopic.addToResourcePolicy(
      new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal("ses.amazonaws.com")],
        actions: ["sns:Publish"],
        resources: [outreachEventsTopic.topicArn],
        conditions: {
          StringEquals: { "AWS:SourceAccount": this.account },
        },
      })
    );
    // SES event destinations must GenerateDataKey on a CMK-encrypted topic.
    this.sharedEncryptionKey.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "AllowSesOutreachEventEncryption",
        principals: [new iam.ServicePrincipal("ses.amazonaws.com")],
        actions: ["kms:Decrypt", "kms:GenerateDataKey*"],
        resources: ["*"],
        conditions: {
          StringEquals: { "aws:SourceAccount": this.account },
        },
      })
    );
    outreachEventsTopic.addSubscription(new snsSubs.SqsSubscription(outreachEventsQueue));
    const outreachConfigSet = new ses.ConfigurationSet(this, "SiutindeiOutreachConfigSet", {
      configurationSetName: "lxsoftware-admin-siutindei-outreach",
    });
    outreachConfigSet.addEventDestination("OutreachSesEvents", {
      destination: ses.EventDestination.snsTopic(outreachEventsTopic),
      events: [
        ses.EmailSendingEvent.BOUNCE,
        ses.EmailSendingEvent.COMPLAINT,
        ses.EmailSendingEvent.REJECT,
      ],
    });
    const newsletterConfigSet = new ses.ConfigurationSet(this, "SiutindeiNewsletterConfigSet", {
      configurationSetName: "lxsoftware-admin-siutindei-newsletter",
    });
    newsletterConfigSet.addEventDestination("NewsletterSesEvents", {
      destination: ses.EventDestination.snsTopic(outreachEventsTopic),
      events: [
        ses.EmailSendingEvent.BOUNCE,
        ses.EmailSendingEvent.COMPLAINT,
        ses.EmailSendingEvent.REJECT,
        ses.EmailSendingEvent.OPEN,
        ses.EmailSendingEvent.CLICK,
      ],
    });
    adminFn.addEventSource(
      new lambdaEventSources.SqsEventSource(outreachEventsQueue, { batchSize: 10 })
    );
    new ses.CfnEmailIdentity(this, "SiutindeiOutreachSendingIdentity", {
      emailIdentity: outreachSendingDomain.valueAsString,
      dkimAttributes: { signingEnabled: true },
      mailFromAttributes: {
        mailFromDomain: cdk.Fn.join(".", ["mail", outreachSendingDomain.valueAsString]),
        behaviorOnMxFailure: "USE_DEFAULT_VALUE",
      },
    });
    adminFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["ses:SendEmail", "ses:SendRawEmail", "ses:GetEmailIdentity"],
        resources: [
          cdk.Stack.of(this).formatArn({
            service: "ses",
            resource: "identity",
            resourceName: outreachSendingDomain.valueAsString,
          }),
        ],
      })
    );

    // Daily unattended balance refresh (05:30 HKT). The handler no-ops when
    // ENABLE_BANKING_APP_ID is blank, so the rule is safe to keep enabled.
    new events.Rule(this, "BankSyncDailyRule", {
      description:
        "Daily Enable Banking balance sync into the finance accounts sheet.",
      schedule: events.Schedule.cron({ minute: "30", hour: "21" }),
      targets: [
        new eventsTargets.LambdaFunction(adminFn, {
          event: events.RuleTargetInput.fromObject({ internal: "bank_sync" }),
        }),
      ],
    });

    // Self-invoke worker name: handler falls back to the Lambda runtime's
    // built-in `AWS_LAMBDA_FUNCTION_NAME` env var when `PARSE_WORKER_FUNCTION_NAME`
    // is unset, so we deliberately do NOT add a self-referencing env var here
    // (`addEnvironment("PARSE_WORKER_FUNCTION_NAME", adminFn.functionName)` would
    // make AdminApiFn depend on itself via `Ref`, which CloudFormation rejects
    // as a circular dependency).

    new lambda.EventInvokeConfig(this, "AdminApiAsyncInvoke", {
      function: adminFn,
      retryAttempts: 0,
      maxEventAge: cdk.Duration.minutes(10),
    });

    // Self-invoke permission for async parse worker. Using
    // `adminFn.grantInvoke(adminFn)` would add a `Fn::GetAtt` of the function
    // ARN into the function's own role default policy, while CDK adds a
    // `DependsOn: AdminApiFnServiceRoleDefaultPolicy` on the function — that
    // pair forms a circular dependency. Construct the resource ARN from the
    // stack's pseudo-parameters (no Ref/GetAtt on the function itself) to
    // break the cycle. The wildcard is acceptable because the role is
    // attached only to this Lambda, whose code is the sole consumer.
    const selfInvokeArn = cdk.Stack.of(this).formatArn({
      service: "lambda",
      resource: "function",
      resourceName: "*",
      arnFormat: cdk.ArnFormat.COLON_RESOURCE_NAME,
    });
    new iam.Policy(this, "AdminApiFnSelfInvokePolicy", {
      statements: [
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["lambda:InvokeFunction"],
          resources: [selfInvokeArn],
        }),
      ],
    }).attachToRole(adminFn.role!);

    // Allow async-invocation DLQ writes from this function.
    this.lambdaDeadLetterQueue.grantSendMessages(adminFn);

    this.recordsTable.grantReadWriteData(adminFn);
    this.assetsBucket.grantReadWrite(adminFn);

    // Grant SecretsManager:GetSecretValue only when an ARN is provided.
    // We can't conditionally call grantRead() from a CfnParameter, so we
    // attach a narrow IAM policy that resolves to the parameter value at
    // deploy time. When the ARN is blank, the resource list collapses to
    // an empty string and the action is effectively a no-op.
    const openRouterSecretArnValue = openRouterApiKeySecretArn.valueAsString;
    const hasOpenRouterSecret = new cdk.CfnCondition(
      this,
      "HasOpenRouterSecret",
      {
        expression: cdk.Fn.conditionNot(
          cdk.Fn.conditionEquals(openRouterSecretArnValue, "")
        ),
      }
    );
    const openRouterSecretPolicy = new iam.Policy(this, "AdminOpenRouterSecretPolicy", {
      statements: [
        new iam.PolicyStatement({
          actions: ["secretsmanager:GetSecretValue"],
          resources: [openRouterSecretArnValue],
        }),
      ],
    });
    openRouterSecretPolicy.attachToRole(adminFn.role!);
    const cfnSecretPolicy = openRouterSecretPolicy.node.defaultChild as iam.CfnPolicy;
    cfnSecretPolicy.cfnOptions.condition = hasOpenRouterSecret;

    siutindeiBoardSecrets.github.grantRead(adminFn);
    siutindeiBoardSecrets.search.grantRead(adminFn);
    siutindeiBoardSecrets.metaToken.grantRead(adminFn);
    siutindeiBoardSecrets.metaAppSecret.grantRead(adminFn);
    siutindeiBoardSecrets.appStore.grantRead(adminFn);
    siutindeiBoardSecrets.play.grantRead(adminFn);
    siutindeiBoardSecrets.analytics.grantRead(adminFn);
    googlePlacesKeySecret.grantRead(adminFn);
    boardLinkSigningSecret.grantRead(adminFn);

    // Executive Board aws + security read tools (plan §8). Each statement is
    // scoped as tightly as the IAM action allows (see the Service
    // Authorization Reference); the handler additionally filters CloudWatch
    // results to the siutindei stacks in code.
    new iam.Policy(this, "SiutindeiBoardAwsReadPolicy", {
      statements: [
        // Cost Explorer, Health, and the CloudWatch metrics/alarm-list APIs
        // do not support resource-level permissions, so "*" is the only
        // valid resource for these actions.
        new iam.PolicyStatement({
          sid: "AccountScopedReadApis",
          actions: [
            "ce:GetCostAndUsage",
            "health:DescribeEvents",
            "cloudwatch:DescribeAlarms",
            "cloudwatch:GetMetricData",
          ],
          resources: ["*"],
        }),
        // board_security.py only calls describe_user_pool on USER_POOL_ID,
        // which is this stack's pool.
        new iam.PolicyStatement({
          sid: "CognitoDescribeOwnUserPool",
          actions: ["cognito-idp:DescribeUserPool"],
          resources: [this.auth.userPool.userPoolArn],
        }),
        // GetFindings is authorised against the regional `hub/default`
        // resource; the handler uses the Lambda's own region.
        new iam.PolicyStatement({
          sid: "SecurityHubGetFindings",
          actions: ["securityhub:GetFindings"],
          resources: [
            cdk.Stack.of(this).formatArn({
              service: "securityhub",
              resource: "hub",
              resourceName: "default",
              arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
            }),
          ],
        }),
        // ListFindings is scoped to the analyzer ARN (the handler picks the
        // first analyzer in this region); ListAnalyzers has no resource type
        // and therefore must stay on "*".
        new iam.PolicyStatement({
          sid: "AccessAnalyzerListFindings",
          actions: ["access-analyzer:ListFindings"],
          resources: [
            cdk.Stack.of(this).formatArn({
              service: "access-analyzer",
              resource: "analyzer",
              resourceName: "*",
              arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
            }),
          ],
        }),
        new iam.PolicyStatement({
          sid: "AccessAnalyzerListAnalyzers",
          actions: ["access-analyzer:ListAnalyzers"],
          resources: ["*"],
        }),
      ],
    }).attachToRole(adminFn.role!);

    const hasSiutindeiDataApi = new cdk.CfnCondition(this, "HasSiutindeiDataApi", {
      expression: cdk.Fn.conditionAnd(
        cdk.Fn.conditionNot(cdk.Fn.conditionEquals(siutindeiClusterArn.valueAsString, "")),
        cdk.Fn.conditionNot(cdk.Fn.conditionEquals(siutindeiDbSecretArn.valueAsString, ""))
      ),
    });
    const dataApiPolicy = new iam.Policy(this, "AdminSiutindeiDataApiPolicy", {
      statements: [
        new iam.PolicyStatement({
          actions: ["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
          resources: [siutindeiClusterArn.valueAsString],
        }),
        new iam.PolicyStatement({
          actions: ["secretsmanager:GetSecretValue"],
          resources: [siutindeiDbSecretArn.valueAsString],
        }),
      ],
    });
    dataApiPolicy.attachToRole(adminFn.role!);
    (dataApiPolicy.node.defaultChild as iam.CfnPolicy).cfnOptions.condition = hasSiutindeiDataApi;

    // ------------------------------------------------------------------
    // Inbound mail: SES → S3 (raw) → Lambda extracts PDF → same parser as UI
    // ------------------------------------------------------------------
    const inboundMailDomain = new cdk.CfnParameter(this, "InboundMailDomain", {
      type: "String",
      default: "inbound.lx-software.com",
      description:
        "Domain for receiving statement mail (verify domain + MX to SES in this region before use).",
    });

    /**
     * Raw objects land at ``<inboundRawMailPrefix>/<houseKey>/…``. Lambda env
     * ``INBOUND_RAW_MAIL_PREFIX`` must match ``inboundRawMailPrefix``.
     */
    const inboundRawMailPrefix = "inbound-raw";

    /**
     * Map each inbox local-part to a finance house key (must match
     * ``FINANCE_HOUSE_KEYS`` / ``HouseKey`` in the admin app). Display names
     * differ: e.g. "32 Hillmarton" in the UI uses key ``hillmarton``; the
     * Morrison house uses key ``morrison``.
     */
    const inboundHouseMailboxes: ReadonlyArray<{
      readonly localPart: string;
      readonly houseKey: string;
    }> = [
      { localPart: "32-hillmarton", houseKey: "hillmarton" },
      // { localPart: "the-morrison", houseKey: "morrison" },
    ];

    const inboundMailBucketName = [
      "lxsoftware-admin-inbound-mail",
      cdk.Aws.ACCOUNT_ID,
      cdk.Aws.REGION,
    ].join("-");

    const inboundMailBucket = new s3.Bucket(this, "InboundMailBucket", {
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

    const inboundStatementFn = createPythonLambda(this, "InboundStatementMailFn", {
      entryDir: path.join(__dirname, "..", "..", "lambda", "admin"),
      handler: "inbound_email_handler.lambda_handler",
      timeout: adminStatementParseLambdaTimeout,
      memorySize: 1024,
      environmentEncryptionKey: this.sharedEncryptionKey,
      logEncryptionKey: this.sharedEncryptionKey,
      deadLetterQueue: this.lambdaDeadLetterQueue,
      environment: {
        RECORDS_TABLE_NAME: this.recordsTable.tableName,
        AUDIT_LOG_TABLE_NAME: this.auditLogTable.tableName,
        ASSETS_BUCKET_NAME: this.assetsBucket.bucketName,
        INBOUND_MAIL_BUCKET_NAME: inboundMailBucket.bucketName,
        INBOUND_RAW_MAIL_PREFIX: inboundRawMailPrefix,
        INBOUND_AUDIT_USER_SUB: "inbound-email",
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

    this.recordsTable.grantReadWriteData(inboundStatementFn);
    this.auditLogTable.grantReadWriteData(inboundStatementFn);
    this.assetsBucket.grantReadWrite(inboundStatementFn);
    inboundMailBucket.grantRead(inboundStatementFn);
    inboundMailBucket.grantDelete(inboundStatementFn);
    openRouterSecretPolicy.attachToRole(inboundStatementFn.role!);
    this.lambdaDeadLetterQueue.grantSendMessages(inboundStatementFn);

    adminFn.grantInvoke(inboundStatementFn);

    // AdminApiFn is invoked asynchronously for OpenRouter work (self-invoke from
    // the HTTP API + invoke from InboundStatementMailFn). A future split to
    // SQS + a dedicated parser Lambda would separate concurrency from API routes;
    // this stack keeps a single code bundle for low admin traffic.

    const inboundReceiptRuleSet = new ses.ReceiptRuleSet(this, "InboundMailReceiptRuleSet", {
      receiptRuleSetName: "lxsoftware-inbound-mail",
    });

    for (const mailbox of inboundHouseMailboxes) {
      const rawKeyPrefix = `${inboundRawMailPrefix}/${mailbox.houseKey}/`;

      inboundStatementFn.addEventSource(
        new lambdaEventSources.S3EventSource(inboundMailBucket, {
          events: [s3.EventType.OBJECT_CREATED],
          filters: [{ prefix: rawKeyPrefix }],
        })
      );

      inboundReceiptRuleSet.addRule(`InboundMailbox-${mailbox.houseKey}`, {
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
    // Executive Board mail: every BoardMailDomain mailbox is copied here by a
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

    // ------------------------------------------------------------------
    // Evolve Sprouts invoices share this rule set. SES allows only one
    // active receipt rule set per region; the evolvesprouts stack used to
    // create and activate its own set, which hid hillmarton + board mail.
    // The ES processor / bucket / SNS topic stay in that repo. This rule
    // keeps the same SES receipt-rule name so ES bucket/role/KMS policies
    // can allow both SourceArns during the cutover.
    // ------------------------------------------------------------------
    const evolvesproutsInvoiceRecipient = new cdk.CfnParameter(
      this,
      "EvolvesproutsInboundInvoiceRecipient",
      {
        type: "String",
        default: "invoices@inbound.evolvesprouts.com",
        description:
          "SES recipient for Evolve Sprouts invoice automation (iCloud forwards invoices@evolvesprouts.com here).",
      }
    );
    const evolvesproutsInvoiceReceiptRoleName = new cdk.CfnParameter(
      this,
      "EvolvesproutsInboundInvoiceReceiptRoleName",
      {
        type: "String",
        default: "evolvesprouts-InboundInvoiceReceiptRoleBA3C88C4-9AWbAAtiZBZS",
        description:
          "Physical IAM role name from the evolvesprouts stack. SES assumes it to write invoice mail to the ES assets bucket and publish SNS.",
      }
    );
    const evolvesproutsInvoiceRuleName = "evolvesprouts-inbound-invoice-email-rule";
    const evolvesproutsInvoiceRawPrefix = "inbound-email/raw/";
    const evolvesproutsAssetsBucketName = cdk.Fn.join("-", [
      "evolvesprouts-assets",
      cdk.Aws.ACCOUNT_ID,
      cdk.Aws.REGION,
    ]);
    const evolvesproutsInvoiceTopicArn = cdk.Stack.of(this).formatArn({
      service: "sns",
      resource: "evolvesprouts-inbound-invoice-email-events",
    });
    const evolvesproutsInvoiceReceiptRoleArn = cdk.Stack.of(this).formatArn({
      service: "iam",
      region: "",
      resource: "role",
      resourceName: evolvesproutsInvoiceReceiptRoleName.valueAsString,
    });

    const evolvesproutsInvoiceRule = new ses.CfnReceiptRule(
      this,
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
      this,
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

    for (const fn of [adminFn, inboundStatementFn]) {
      fn.addEnvironment("BOARD_MAIL_DOMAIN", boardMailDomain.valueAsString);
      fn.addEnvironment("BOARD_MAIL_RAW_SEGMENT", boardMailRawSegment);
      fn.addEnvironment("BOARD_MAIL_INBOUND_ADDRESS", boardMailInboundAddress);
    }

    // Sending identity for BoardMailDomain, created only once the owner flips
    // BoardMailSendingEnabled (DNS must carry the DKIM CNAMEs first). The send
    // policy is scoped to that single identity so the board can never send
    // from anything but the company domain.
    const hasBoardMailSending = new cdk.CfnCondition(this, "HasBoardMailSending", {
      expression: cdk.Fn.conditionEquals(
        boardMailSendingEnabled.valueAsString,
        "true"
      ),
    });
    const boardMailIdentity = new ses.CfnEmailIdentity(this, "SiutindeiBoardMailSendingIdentity", {
      emailIdentity: boardMailDomain.valueAsString,
      dkimAttributes: { signingEnabled: true },
      mailFromAttributes: { behaviorOnMxFailure: "USE_DEFAULT_VALUE" },
    });
    boardMailIdentity.cfnOptions.condition = hasBoardMailSending;
    const boardMailSendPolicy = new iam.Policy(this, "SiutindeiBoardMailSendPolicy", {
      statements: [
        new iam.PolicyStatement({
          actions: ["ses:SendEmail", "ses:SendRawEmail", "ses:SendBulkEmail"],
          resources: [
            cdk.Stack.of(this).formatArn({
              service: "ses",
              resource: "identity",
              resourceName: boardMailDomain.valueAsString,
            }),
          ],
        }),
        new iam.PolicyStatement({
          actions: ["ses:CreateEmailTemplate", "ses:GetEmailTemplate", "ses:UpdateEmailTemplate"],
          resources: ["*"],
        }),
      ],
    });
    boardMailSendPolicy.attachToRole(adminFn.role!);
    const cfnBoardMailSendPolicy = boardMailSendPolicy.node.defaultChild as iam.CfnPolicy;
    cfnBoardMailSendPolicy.cfnOptions.condition = hasBoardMailSending;

    // AWS::ApiGatewayV2::Integration TimeoutInMillis must be 50–30000 ms in this
    // account/region; CDK defaults (~29s). Do not raise via L1 overrides.
    const integration = new SharedPermissionLambdaIntegration(
      "AdminIntegration",
      adminFn
    );

    this.httpApi = new apigwv2.HttpApi(this, "HttpApi", {
      apiName: "lxsoftware-admin-api",
      corsPreflight: {
        allowHeaders: ["authorization", "content-type", "x-api-key"],
        allowMethods: [
          apigwv2.CorsHttpMethod.GET,
          apigwv2.CorsHttpMethod.POST,
          apigwv2.CorsHttpMethod.PUT,
          apigwv2.CorsHttpMethod.DELETE,
          apigwv2.CorsHttpMethod.OPTIONS,
        ],
        allowOrigins: [
          cdk.Fn.join("", ["https://", adminWebDomainName.valueAsString]),
        ],
        allowCredentials: false,
      },
    });

    // One invoke permission for every route of this API (any stage, method
    // and path), scoped to this API's execute-api ARN so no other API
    // Gateway can invoke the function. Keep the construct id short and at
    // stack scope: CloudFormation uses "<stack>-<logicalId>-<random>" as the
    // policy statement id, and the statement must fit in the ~400 bytes left
    // in the 20 KB policy while the old per-route statements still exist.
    adminFn.addPermission("AdminApiInvoke", {
      scope: this,
      principal: new iam.ServicePrincipal("apigateway.amazonaws.com"),
      sourceArn: this.httpApi.arnForExecuteApi(),
    });

    const accessLogGroup = new logs.LogGroup(this, "HttpApiAccessLogs", {
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      // CKV_AWS_158: encrypt at rest with the stack's shared CMK. The
      // CloudWatch Logs service principal is granted Encrypt*/Decrypt*
      // on the key in the stack-level policy above.
      encryptionKey: this.sharedEncryptionKey,
    });

    accessLogGroup.addToResourcePolicy(
      new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal("apigateway.amazonaws.com")],
        actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
        resources: [`${accessLogGroup.logGroupArn}:*`],
      })
    );

    const defaultStage = this.httpApi.defaultStage?.node
      .defaultChild as apigwv2.CfnStage;
    defaultStage.accessLogSettings = {
      destinationArn: accessLogGroup.logGroupArn,
      format: JSON.stringify({
        requestId: "$context.requestId",
        routeKey: "$context.routeKey",
        status: "$context.status",
        integrationError: "$context.integrationErrorMessage",
        authorizerError: "$context.authorizer.error",
        httpMethod: "$context.httpMethod",
        path: "$context.path",
        sourceIp: "$context.identity.sourceIp",
        // Populated by HttpJwtAuthorizer; lets us correlate 4xx with the
        // specific Cognito identity / token without having to add per-handler logs.
        claimSub: "$context.authorizer.claims.sub",
        claimEmail: "$context.authorizer.claims.email",
        claimGroups: "$context.authorizer.claims.cognito:groups",
        claimTokenUse: "$context.authorizer.claims.token_use",
      }),
    };

    // Stage-level throttling. The admin SPA is a handful of concurrent
    // operators polling a few endpoints (parse-job status every couple of
    // seconds, board chat, dashboards), so 50 req/s sustained with a 100
    // burst is far above normal use while still capping a runaway client.
    // The unauthenticated Meta webhook routes get a much tighter per-route
    // limit so an anonymous caller cannot drive Lambda invocations at the
    // stage rate; Meta retries delivery on 429, so brief throttling is safe.
    defaultStage.defaultRouteSettings = {
      throttlingRateLimit: 50,
      throttlingBurstLimit: 100,
    };
    const webhookRouteThrottle = {
      ThrottlingRateLimit: 10,
      ThrottlingBurstLimit: 20,
    };
    defaultStage.routeSettings = {
      "POST /webhooks/meta": webhookRouteThrottle,
      "GET /webhooks/meta": webhookRouteThrottle,
      "POST /webhooks/meta/siutindei": webhookRouteThrottle,
      "GET /webhooks/meta/siutindei": webhookRouteThrottle,
      "GET /public/outreach/unsubscribe/{token}": webhookRouteThrottle,
      "POST /public/outreach/unsubscribe/{token}": webhookRouteThrottle,
      "POST /public/newsletter/subscribe": webhookRouteThrottle,
      "GET /public/newsletter/confirm/{token}": webhookRouteThrottle,
      "GET /public/newsletter/unsubscribe/{token}": webhookRouteThrottle,
      "POST /public/newsletter/unsubscribe/{token}": webhookRouteThrottle,
    };

    this.httpApi.addRoutes({
      path: "/health",
      methods: [apigwv2.HttpMethod.GET],
      integration,
    });

    // First non-JWT admin routes. Tenant path is canonical; /webhooks/meta
    // stays so an already-subscribed Meta app keeps working.
    const metaWebhookRoutes = this.httpApi.addRoutes({
      path: "/webhooks/meta",
      methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      integration,
    });
    const siutindeiMetaWebhookRoutes = this.httpApi.addRoutes({
      path: "/webhooks/meta/siutindei",
      methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      integration,
    });
    // API Gateway V2 rejects RouteSettings keys until the Route exists.
    // CloudFormation can update DefaultStage before creating new routes in
    // the same changeset (that left lxsoftware UPDATE_ROLLBACK_FAILED on
    // the first /webhooks/meta/siutindei deploy). Pin the stage to the
    // throttled routes so settings land after GET/POST exist.
    const outreachUnsubRoutes = this.httpApi.addRoutes({
      path: "/public/outreach/unsubscribe/{token}",
      methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      integration,
    });
    const newsletterSubscribeRoutes = this.httpApi.addRoutes({
      path: "/public/newsletter/subscribe",
      methods: [apigwv2.HttpMethod.POST],
      integration,
    });
    const newsletterConfirmRoutes = this.httpApi.addRoutes({
      path: "/public/newsletter/confirm/{token}",
      methods: [apigwv2.HttpMethod.GET],
      integration,
    });
    const newsletterUnsubRoutes = this.httpApi.addRoutes({
      path: "/public/newsletter/unsubscribe/{token}",
      methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      integration,
    });
    for (const route of [
      ...metaWebhookRoutes,
      ...siutindeiMetaWebhookRoutes,
      ...outreachUnsubRoutes,
      ...newsletterSubscribeRoutes,
      ...newsletterConfirmRoutes,
      ...newsletterUnsubRoutes,
    ]) {
      defaultStage.addResourceDependency(route.node.defaultChild as apigwv2.CfnRoute);
    }
    const hasPublicApiBaseUrl = new cdk.CfnCondition(this, "HasPublicApiBaseUrl", {
      expression: cdk.Fn.conditionNot(
        cdk.Fn.conditionEquals(publicApiBaseUrl.valueAsString, "")
      ),
    });
    adminFn.addEnvironment(
      "PUBLIC_API_BASE_URL",
      cdk.Fn.conditionIf(
        hasPublicApiBaseUrl.logicalId,
        publicApiBaseUrl.valueAsString,
        this.httpApi.apiEndpoint
      ).toString()
    );

    this.httpApi.addRoutes({
      path: "/me",
      methods: [apigwv2.HttpMethod.GET],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/fx/v2/rates",
      methods: [apigwv2.HttpMethod.GET],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/assets/upload-url",
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/assets/confirm",
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/assets/download-url",
      methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/assets/delete",
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/records",
      methods: [
        apigwv2.HttpMethod.GET,
        apigwv2.HttpMethod.POST,
        apigwv2.HttpMethod.PUT,
      ],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance",
      methods: [apigwv2.HttpMethod.GET],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/quotes",
      methods: [apigwv2.HttpMethod.GET],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/income",
      methods: [apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/expenses",
      methods: [apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/investments",
      methods: [apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/savings",
      methods: [apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/pension",
      methods: [apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/accounts",
      methods: [apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/liabilities",
      methods: [apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/allocations",
      methods: [apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/{house}",
      methods: [apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/{house}/parse-statement",
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/finance/{house}/parse-statement/jobs/{jobId}",
      methods: [apigwv2.HttpMethod.GET],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/siu-tin-dei",
      methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/siu-tin-dei/parse-statement",
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/siu-tin-dei/parse-statement/jobs/{jobId}",
      methods: [apigwv2.HttpMethod.GET],
      integration,
      authorizer: jwtAuthorizer,
    });

    // Executive Board (admin JWT only; never mirrored under /public/*).
    const boardRoutes: ReadonlyArray<{
      readonly path: string;
      readonly methods: readonly apigwv2.HttpMethod[];
    }> = [
      { path: "/siu-tin-dei/board", methods: [apigwv2.HttpMethod.GET] },
      { path: "/siu-tin-dei/board/charter", methods: [apigwv2.HttpMethod.PUT] },
      {
        path: "/siu-tin-dei/board/members/{personaId}",
        methods: [apigwv2.HttpMethod.PUT, apigwv2.HttpMethod.DELETE],
      },
      { path: "/siu-tin-dei/board/brief", methods: [apigwv2.HttpMethod.PUT] },
      { path: "/siu-tin-dei/board/settings", methods: [apigwv2.HttpMethod.PUT] },
      {
        path: "/siu-tin-dei/board/updates",
        methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/chat/{personaId}",
        methods: [
          apigwv2.HttpMethod.GET,
          apigwv2.HttpMethod.POST,
          apigwv2.HttpMethod.DELETE,
        ],
      },
      {
        path: "/siu-tin-dei/board/chat/{personaId}/jobs/{jobId}",
        methods: [apigwv2.HttpMethod.GET],
      },
      {
        path: "/siu-tin-dei/board/meetings",
        methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/meetings/{meetingId}",
        methods: [apigwv2.HttpMethod.GET],
      },
      {
        path: "/siu-tin-dei/board/meetings/{meetingId}/cancel",
        methods: [apigwv2.HttpMethod.POST],
      },
      { path: "/siu-tin-dei/board/actions", methods: [apigwv2.HttpMethod.GET] },
      {
        path: "/siu-tin-dei/board/actions/{actionId}",
        methods: [apigwv2.HttpMethod.PUT],
      },
      {
        path: "/siu-tin-dei/board/repo-snapshot/refresh",
        methods: [apigwv2.HttpMethod.POST],
      },
      // Tools and permissions (docs/architecture/executive-board-tools-plan.md)
      {
        path: "/siu-tin-dei/board/tools",
        methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.PUT],
      },
      {
        path: "/siu-tin-dei/board/tools/calls",
        methods: [apigwv2.HttpMethod.GET],
      },
      {
        path: "/siu-tin-dei/board/approvals",
        methods: [apigwv2.HttpMethod.GET],
      },
      {
        path: "/siu-tin-dei/board/approvals/{approvalId}/approve",
        methods: [apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/approvals/{approvalId}/reject",
        methods: [apigwv2.HttpMethod.POST],
      },
      // Company mail index (owner view; personas use the mail tools)
      { path: "/siu-tin-dei/board/mail", methods: [apigwv2.HttpMethod.GET] },
      {
        path: "/siu-tin-dei/board/mail/{threadId}",
        methods: [apigwv2.HttpMethod.GET],
      },
      {
        path: "/siu-tin-dei/board/mail/{threadId}/read",
        methods: [apigwv2.HttpMethod.POST],
      },
      { path: "/siu-tin-dei/board/receivables", methods: [apigwv2.HttpMethod.GET] },
      { path: "/siu-tin-dei/board/staff", methods: [apigwv2.HttpMethod.GET] },
      {
        path: "/siu-tin-dei/board/staff/{seatId}",
        methods: [apigwv2.HttpMethod.PUT, apigwv2.HttpMethod.DELETE],
      },
      {
        path: "/siu-tin-dei/board/tasks",
        methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      },
      { path: "/siu-tin-dei/board/tasks/{taskId}", methods: [apigwv2.HttpMethod.GET] },
      {
        path: "/siu-tin-dei/board/tasks/{taskId}/cancel",
        methods: [apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/tasks/{taskId}/review",
        methods: [apigwv2.HttpMethod.POST],
      },
      { path: "/siu-tin-dei/board/holds", methods: [apigwv2.HttpMethod.GET] },
      {
        path: "/siu-tin-dei/board/holds/{holdId}/veto",
        methods: [apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/holds/veto-class",
        methods: [apigwv2.HttpMethod.POST],
      },
      { path: "/siu-tin-dei/board/boundaries", methods: [apigwv2.HttpMethod.PUT] },
      { path: "/siu-tin-dei/board/ramp", methods: [apigwv2.HttpMethod.GET] },
      {
        path: "/siu-tin-dei/board/ramp/{classKey}/promote",
        methods: [apigwv2.HttpMethod.POST],
      },
      { path: "/siu-tin-dei/board/review", methods: [apigwv2.HttpMethod.GET] },
      {
        path: "/siu-tin-dei/board/review/sample/{callId}/wrong",
        methods: [apigwv2.HttpMethod.POST],
      },
      { path: "/siu-tin-dei/board/lessons", methods: [apigwv2.HttpMethod.GET] },
      {
        path: "/siu-tin-dei/board/lessons/{lessonId}/confirm",
        methods: [apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/lessons/{lessonId}/dismiss",
        methods: [apigwv2.HttpMethod.POST],
      },
      { path: "/siu-tin-dei/board/breakers", methods: [apigwv2.HttpMethod.GET] },
      {
        path: "/siu-tin-dei/board/breakers/{name}/reset",
        methods: [apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/watchlist",
        methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/watchlist/{watchId}",
        methods: [apigwv2.HttpMethod.PUT, apigwv2.HttpMethod.DELETE],
      },
      { path: "/siu-tin-dei/board/changes", methods: [apigwv2.HttpMethod.GET] },
      {
        path: "/siu-tin-dei/board/prospects",
        methods: [apigwv2.HttpMethod.GET],
      },
      {
        path: "/siu-tin-dei/board/prospects/import",
        methods: [apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/prospects/{id}",
        methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.PUT],
      },
      {
        path: "/siu-tin-dei/board/prospects/{id}/merge",
        methods: [apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/sequences/{type}",
        methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.PUT],
      },
      {
        path: "/siu-tin-dei/board/outreach/stats",
        methods: [apigwv2.HttpMethod.GET],
      },
      {
        path: "/siu-tin-dei/board/content",
        methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/content/{id}",
        methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.PUT],
      },
      {
        path: "/siu-tin-dei/board/content/{id}/render",
        methods: [apigwv2.HttpMethod.POST],
      },
      {
        path: "/siu-tin-dei/board/content/{id}/creative/{n}",
        methods: [apigwv2.HttpMethod.GET],
      },
    ];
    for (const route of boardRoutes) {
      this.httpApi.addRoutes({
        path: route.path,
        methods: [...route.methods],
        integration,
        authorizer: jwtAuthorizer,
      });
    }

    this.httpApi.addRoutes({
      path: "/lx-software",
      methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/lx-software/parse-statement",
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/lx-software/parse-statement/jobs/{jobId}",
      methods: [apigwv2.HttpMethod.GET],
      integration,
      authorizer: jwtAuthorizer,
    });

    // Enable Banking sync management (admin JWT only; never mirrored under
    // /public/*: these routes can move money-adjacent consent state).
    this.httpApi.addRoutes({
      path: "/banking",
      methods: [apigwv2.HttpMethod.GET],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/banking/banks",
      methods: [apigwv2.HttpMethod.GET],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/banking/auth",
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/banking/sessions",
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/banking/sessions/{sessionId}",
      methods: [apigwv2.HttpMethod.DELETE],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/banking/mappings",
      methods: [apigwv2.HttpMethod.PUT],
      integration,
      authorizer: jwtAuthorizer,
    });

    this.httpApi.addRoutes({
      path: "/banking/sync",
      methods: [apigwv2.HttpMethod.POST],
      integration,
      authorizer: jwtAuthorizer,
    });

    /**
     * Read-only mirrors of the admin GET endpoints under /public/*,
     * authenticated with a static API key (`x-api-key` header) instead of a
     * Cognito JWT. The handler enforces the same allowlist
     * (`PUBLIC_READ_PATHS` in backend/lambda/admin/dispatch.py) as defense
     * in depth. Assets and parse-job routes are intentionally not mirrored.
     */
    const publicReadOnlyPaths = [
      "/public/finance",
      "/public/finance/quotes",
      "/public/records",
      "/public/fx/v2/rates",
    ];
    for (const publicPath of publicReadOnlyPaths) {
      this.httpApi.addRoutes({
        path: publicPath,
        methods: [apigwv2.HttpMethod.GET],
        integration,
        authorizer: publicApiKeyAuthorizer,
      });
    }

    // ------------------------------------------------------------------
    // CloudFormation outputs (export names kept stable for compatibility
    // with downstream consumers / dashboards / runbooks).
    // ------------------------------------------------------------------
    new cdk.CfnOutput(this, "UserPoolId", {
      value: this.auth.userPool.userPoolId,
      exportName: "lxsoftware-UserPoolId",
    });

    new cdk.CfnOutput(this, "UserPoolClientId", {
      value: this.auth.userPoolClient.userPoolClientId,
      exportName: "lxsoftware-UserPoolClientId",
    });

    new cdk.CfnOutput(this, "UserPoolArn", {
      value: this.auth.userPool.userPoolArn,
      exportName: "lxsoftware-UserPoolArn",
    });

    new cdk.CfnOutput(this, "CognitoDomain", {
      value: this.auth.cognitoOAuthBaseUrl,
      description: "Full https URL for Cognito hosted UI / OAuth.",
      exportName: "lxsoftware-CognitoDomain",
    });

    const cognitoCustomDomainCloudFront = new cdk.CfnOutput(
      this,
      "CognitoCustomDomainCloudFront",
      {
        value: this.auth.cognitoCustomHostedDomain.attrCloudFrontDistribution,
        description:
          "CNAME target for the Cognito custom Hosted UI domain (ACM + DNS).",
        exportName: "lxsoftware-CognitoCustomDomainCloudFront",
      }
    );
    cognitoCustomDomainCloudFront.condition = this.auth.useCustomAuthDomain;

    new cdk.CfnOutput(this, "RecordsTableName", {
      value: this.recordsTable.tableName,
      exportName: "lxsoftware-RecordsTableName",
    });

    new cdk.CfnOutput(this, "RecordsTableArn", {
      value: this.recordsTable.tableArn,
      exportName: "lxsoftware-RecordsTableArn",
    });

    new cdk.CfnOutput(this, "AuditLogTableName", {
      value: this.auditLogTable.tableName,
      exportName: "lxsoftware-AuditLogTableName",
    });

    new cdk.CfnOutput(this, "AuditLogTableArn", {
      value: this.auditLogTable.tableArn,
      exportName: "lxsoftware-AuditLogTableArn",
    });

    new cdk.CfnOutput(this, "AssetsBucketName", {
      value: this.assetsBucket.bucketName,
      exportName: "lxsoftware-AssetsBucketName",
    });

    new cdk.CfnOutput(this, "AssetsBucketArn", {
      value: this.assetsBucket.bucketArn,
      exportName: "lxsoftware-AssetsBucketArn",
    });

    for (const mailbox of inboundHouseMailboxes) {
      const suffix = mailbox.houseKey.replace(/[^a-zA-Z0-9]/g, "");
      const displayHint =
        mailbox.houseKey === "hillmarton"
          ? 'Statement PDF inbox for "32 Hillmarton"'
          : `Statement PDF inbox (finance house key "${mailbox.houseKey}")`;
      new cdk.CfnOutput(this, `InboundMailboxAddress${suffix}`, {
        value: cdk.Fn.join("", [mailbox.localPart, "@", inboundMailDomain.valueAsString]),
        description: `${displayHint}; DDB/API key is "${mailbox.houseKey}".`,
        exportName: `lxsoftware-InboundMailbox-${mailbox.houseKey}`,
      });
    }

    new cdk.CfnOutput(this, "InboundMailReceiptRuleSetName", {
      value: inboundReceiptRuleSet.receiptRuleSetName,
      description:
        "Shared SES receipt rule set (hillmarton, siutindei-board, Evolve Sprouts invoices). This stack sets it active on deploy.",
      exportName: "lxsoftware-InboundMailReceiptRuleSetName",
    });

    new cdk.CfnOutput(this, "EvolvesproutsInboundInvoiceAddress", {
      value: evolvesproutsInvoiceRecipient.valueAsString,
      description:
        "Invoice mailbox hosted on the shared lxsoftware-inbound-mail rule set; raw MIME still lands in the Evolve Sprouts assets bucket.",
      exportName: "lxsoftware-EvolvesproutsInboundInvoiceAddress",
    });

    new cdk.CfnOutput(this, "InboundMailMxTarget", {
      value: cdk.Fn.join("", ["inbound-smtp.", cdk.Aws.REGION, ".amazonaws.com"]),
      description: "MX record hostname (use priority 10) for the inbound mail domain.",
      exportName: "lxsoftware-InboundMailMxTarget",
    });

    new cdk.CfnOutput(this, "InboundMailBucketName", {
      value: inboundMailBucket.bucketName,
      description: "S3 bucket where SES stores raw inbound messages before processing.",
      exportName: "lxsoftware-InboundMailBucketName",
    });

    new cdk.CfnOutput(this, "SiutindeiBoardMailInboundAddress", {
      value: boardMailInboundAddress,
      description:
        "Destination the Cloudflare Email Worker forwards every BoardMailDomain message to (verify it once in Cloudflare; the verification mail lands in the inbound bucket).",
      exportName: "lxsoftware-SiutindeiBoardMailInboundAddress",
    });

    for (const n of [1, 2, 3] as const) {
      const output = new cdk.CfnOutput(this, `BoardMailDkimCname${n}`, {
        value: cdk.Fn.join(" CNAME ", [
          boardMailIdentity.getAtt(`DkimDNSTokenName${n}`).toString(),
          boardMailIdentity.getAtt(`DkimDNSTokenValue${n}`).toString(),
        ]),
        description: `DKIM CNAME ${n} of 3 to add to the BoardMailDomain zone (name CNAME value).`,
      });
      output.condition = hasBoardMailSending;
    }

    new cdk.CfnOutput(this, "EnableBankingSigningKeyId", {
      value: enableBankingSigningKey.keyId,
      description:
        "KMS key id whose public key must be registered with Enable Banking " +
        "(export PEM: scripts/export-enable-banking-public-key.py).",
      exportName: "lxsoftware-EnableBankingSigningKeyId",
    });

    new cdk.CfnOutput(this, "AdminApiBaseUrl", {
      value: this.httpApi.apiEndpoint,
      description: "Invoke URL for the admin HTTP API.",
      exportName: "lxsoftware-AdminApiBaseUrl",
    });
  }
}
