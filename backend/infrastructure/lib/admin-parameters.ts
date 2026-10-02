import * as cdk from "aws-cdk-lib";
import { ADMIN_WEB_HOSTNAME } from "./shared-contracts";
import { SIUTINDEI_DB_SECRET_NAME_DEFAULT } from "./constructs/siutindei-data-api";

/**
 * CloudFormation parameters for the admin backend stack.
 * Created on the stack itself so logical IDs stay `ParameterName`.
 */
export function defineAdminParameters(scope: cdk.Stack) {
  // ------------------------------------------------------------------
  // CloudFormation parameters
  // ------------------------------------------------------------------
  const adminWebDomainName = new cdk.CfnParameter(scope, "AdminWebDomainName", {
    type: "String",
    description: "Public hostname for the admin SPA (e.g. admin.lx-software.com).",
    default: ADMIN_WEB_HOSTNAME,
  });

  const googleClientId = new cdk.CfnParameter(scope, "GoogleClientId", {
    type: "String",
    description: "Google OAuth client ID for Cognito federation.",
  });

  const googleClientSecret = new cdk.CfnParameter(scope, "GoogleClientSecret", {
    type: "String",
    description: "Google OAuth client secret for Cognito federation.",
    noEcho: true,
  });

  const adminFederatedEmailAllowlist = new cdk.CfnParameter(
    scope,
    "AdminFederatedEmailAllowlist",
    {
      type: "String",
      description:
        "Comma-separated lower-case emails that receive the admin group in tokens (Pre Token Generation). Include every Google admin and the bootstrap email.",
    }
  );

  const adminBootstrapEmail = new cdk.CfnParameter(scope, "AdminBootstrapEmail", {
    type: "String",
    description: "Email for the initial native admin user (bootstrap).",
  });

  const adminBootstrapTempPassword = new cdk.CfnParameter(
    scope,
    "AdminBootstrapTempPassword",
    {
      type: "String",
      description:
        "Temporary password for bootstrap admin (must meet pool policy; rotate after first login).",
      noEcho: true,
    }
  );

  const cognitoDomainPrefix = new cdk.CfnParameter(scope, "CognitoDomainPrefix", {
    type: "String",
    description: "Globally unique Cognito hosted UI domain prefix.",
    default: "lxsoftware-admin-auth",
  });

  const cognitoCustomDomainName = new cdk.CfnParameter(
    scope,
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
    scope,
    "CognitoCustomDomainCertificateArn",
    {
      type: "String",
      default: "",
      description:
        "ACM certificate ARN for the Cognito custom domain (must be in us-east-1).",
    }
  );

  const openRouterApiKeySecretArn = new cdk.CfnParameter(
    scope,
    "OpenRouterApiKeySecretArn",
    {
      type: "String",
      default: "",
      description:
        "ARN of the AWS Secrets Manager secret holding OpenRouter API keys. JSON object with named inference keys (statement-parser, executive-board) plus management (Management API key) so sibling spend can be pulled. Sibling products keep their own named inference keys. Leave blank to disable those features.",
    }
  );

  const openRouterModel = new cdk.CfnParameter(scope, "OpenRouterModel", {
    type: "String",
    default: "mistralai/mistral-medium-3",
    description:
      "OpenRouter model slug used when extracting statement lines from uploaded PDFs.",
  });

  const openRouterPdfEngine = new cdk.CfnParameter(scope, "OpenRouterPdfEngine", {
    type: "String",
    default: "mistral-ocr",
    description:
      "OpenRouter file-parser PDF engine: pdf-text (free, text-based PDFs), mistral-ocr (paid, scanned PDFs), or native (model-native parsing).",
  });

  const enableBankingAppId = new cdk.CfnParameter(scope, "EnableBankingAppId", {
    type: "String",
    default: "",
    description:
      "Enable Banking application id (JWT kid) for the bank account sync. " +
      "Register the app at enablebanking.com with the public key of the " +
      "EnableBankingSigningKey KMS key (docs/deployment/admin-website.md, Enable Banking). " +
      "Leave blank to disable bank sync.",
  });

  // Executive Board (AI board for Siu Tin Dei; see docs/architecture/executive-board.md)
  const siutindeiClusterArn = new cdk.CfnParameter(
    scope,
    "SiutindeiClusterArn",
    {
      type: "String",
      default: "",
      description:
        "Aurora cluster ARN for the siutindei database (RDS Data API). Required for Executive Board finance and product tools.",
    }
  );
  const siutindeiDbSecretArn = new cdk.CfnParameter(
    scope,
    "SiutindeiDbSecretArn",
    {
      type: "String",
      default: "",
      description:
        "Secrets Manager ARN of the siutindei DB credentials used by the RDS Data API. Leave blank to resolve SiutindeiDbSecretName.",
    }
  );
  const siutindeiDbSecretName = new cdk.CfnParameter(
    scope,
    "SiutindeiDbSecretName",
    {
      type: "String",
      default: SIUTINDEI_DB_SECRET_NAME_DEFAULT,
      description:
        "Secrets Manager name of the siutindei DB credentials when SiutindeiDbSecretArn is blank (RDS-owned; do not recreate).",
    }
  );
  const evolvesproutsClusterArn = new cdk.CfnParameter(
    scope,
    "EvolvesproutsClusterArn",
    {
      type: "String",
      default: "",
      description:
        "Aurora cluster ARN for the Evolve Sprouts database (RDS Data API, read-only). Leave blank to keep the Evolve Sprouts statement book idle. Also set a read-only secret (ARN or name); the cluster master secret must not be used.",
    }
  );
  const evolvesproutsDbSecretArn = new cdk.CfnParameter(
    scope,
    "EvolvesproutsDbSecretArn",
    {
      type: "String",
      default: "",
      description:
        "Secrets Manager ARN of a read-only Evolve Sprouts DB user. Leave blank to resolve EvolvesproutsDbSecretName. Do not point this at the cluster master secret.",
    }
  );
  const evolvesproutsDbSecretName = new cdk.CfnParameter(
    scope,
    "EvolvesproutsDbSecretName",
    {
      type: "String",
      default: "",
      description:
        "Secrets Manager name of a read-only Evolve Sprouts DB user when EvolvesproutsDbSecretArn is blank. Leave blank until that user exists. Do not use the cluster master name (evolvesprouts-database-credentials).",
    }
  );
  const siutindeiAdminApiBaseUrl = new cdk.CfnParameter(
    scope,
    "SiutindeiAdminApiBaseUrl",
    {
      type: "String",
      default: "",
      description:
        "Base URL of the siutindei admin HTTP API (no trailing slash). Used by Executive Board catalog import. Leave blank to keep import unconfigured.",
    }
  );
  const siutindeiUserPoolId = new cdk.CfnParameter(scope, "SiutindeiUserPoolId", {
    type: "String",
    default: "",
    description:
      "siutindei Cognito user-pool id for the dedicated importer service user (AdminInitiateAuth). Leave blank until that pool exists.",
  });
  const boardImporterClientId = new cdk.CfnParameter(
    scope,
    "SiutindeiBoardImporterClientId",
    {
      type: "String",
      default: "",
      description:
        "siutindei Cognito app-client id that allows ADMIN_USER_PASSWORD_AUTH for the importer user. Leave blank until the siutindei importer-group PR is deployed.",
    }
  );
  const boardCatalogManagerId = new cdk.CfnParameter(
    scope,
    "SiutindeiBoardCatalogManagerId",
    {
      type: "String",
      default: "",
      description:
        "siutindei manager UUID stamped on every board-imported organisation (required until siutindei default_manager_id ships). Leave blank to keep dry-run local-only.",
    }
  );
  const boardCatalogImportEnabled = new cdk.CfnParameter(
    scope,
    "SiutindeiBoardCatalogImportEnabled",
    {
      type: "String",
      default: "false",
      allowedValues: ["true", "false"],
      description:
        "Kill switch for Executive Board catalog import. Default false (fail-closed): transform and dry-run still work; POST /catalog/import and catalog_import refuse. Flip only after the siutindei importer group, dry_run, and credentials secret are live.",
    }
  );
  const metaVerifyToken = new cdk.CfnParameter(scope, "SiutindeiBoardMetaVerifyToken", {
    type: "String",
    default: "",
    noEcho: true,
    description:
      "Verify token Meta sends on GET /webhooks/meta/siutindei (hub.verify_token). Leave blank to keep the handshake rejected.",
  });
  const metaPageId = new cdk.CfnParameter(scope, "SiutindeiBoardMetaPageId", {
    type: "String",
    default: "",
    description: "Facebook Page id for Executive Board meta tools.",
  });
  const metaIgUserId = new cdk.CfnParameter(scope, "SiutindeiBoardMetaIgUserId", {
    type: "String",
    default: "",
    description: "Instagram professional-account id for Executive Board meta tools.",
  });
  const metaWaPhoneNumberId = new cdk.CfnParameter(
    scope,
    "SiutindeiBoardMetaWaPhoneNumberId",
    {
      type: "String",
      default: "",
      description:
        "WhatsApp Cloud API phone-number id. Enable coexistence so the owner's phone keeps working.",
    }
  );
  const metaAdAccountId = new cdk.CfnParameter(scope, "SiutindeiBoardMetaAdAccountId", {
    type: "String",
    default: "",
    description: "Meta ad account id (with or without act_ prefix).",
  });
  const metaWabaId = new cdk.CfnParameter(scope, "SiutindeiBoardMetaWabaId", {
    type: "String",
    default: "",
    description:
      "WhatsApp Business Account id for listing message templates. Optional if the phone-number id can resolve it.",
  });
  const appStoreConnectAppId = new cdk.CfnParameter(
    scope,
    "SiutindeiBoardAppStoreConnectAppId",
    {
      type: "String",
      default: "",
      description:
        "App Store Connect app id (numeric). May also live inside the AppStoreConnectKey secret.",
    }
  );
  const appStoreConnectVendorNumber = new cdk.CfnParameter(
    scope,
    "SiutindeiBoardAppStoreConnectVendorNumber",
    {
      type: "String",
      default: "",
      description:
        "App Store Connect vendor number used to download daily sales reports (stores_metrics downloads). May also live inside the AppStoreConnectKey secret as vendorNumber.",
    }
  );
  const googlePlayPackageName = new cdk.CfnParameter(
    scope,
    "SiutindeiBoardGooglePlayPackageName",
    {
      type: "String",
      default: "",
      description:
        "Google Play package name (e.g. com.siutindei.app). May also live inside the service-account secret.",
    }
  );
  const ga4PropertyIds = new cdk.CfnParameter(scope, "SiutindeiBoardGa4PropertyIds", {
    type: "String",
    default: "",
    description:
      "Comma-separated GA4 property ids (numeric, with or without a properties/ prefix). Several properties are supported.",
  });
  const gtmContainers = new cdk.CfnParameter(scope, "SiutindeiBoardGtmContainers", {
    type: "String",
    default: "",
    description:
      "Comma-separated GTM account:container pairs (e.g. 123:456,123:789). Used for web_gtm_status.",
  });
  const boardAwsStackPrefix = new cdk.CfnParameter(
    scope,
    "SiutindeiBoardAwsStackPrefix",
    {
      type: "String",
      default: "siutindei",
      description:
        "Name prefix used to match CloudWatch alarms for the Executive Board aws tool. Monthly cost uses the Project cost-allocation tag, not this prefix.",
    }
  );
  const boardAwsLambdaNames = new cdk.CfnParameter(
    scope,
    "SiutindeiBoardAwsLambdaNames",
    {
      type: "String",
      default: "",
      description:
        "Comma-separated Lambda function names (siutindei stack) whose 24h errors/duration the Executive Board aws_lambda_health tool reports. Empty disables the read.",
    }
  );
  const boardToolsEnabled = new cdk.CfnParameter(scope, "SiutindeiBoardToolsEnabled", {
    type: "String",
    default: "true",
    allowedValues: ["true", "false"],
    description:
      "Kill switch for Executive Board tool calls (GitHub, board, mail, research, AWS, security). Set to false to stop every tool call without touching the admin settings.",
  });
  const boardStaffEnabled = new cdk.CfnParameter(scope, "SiutindeiBoardStaffEnabled", {
    type: "String",
    default: "false",
    allowedValues: ["true", "false"],
    description:
      "Kill switch for Executive Board staff tasks. Default false until the task engine and daily review are live. Also requires settings.staff.enabled.",
  });
  const outreachSendingDomain = new cdk.CfnParameter(scope, "SiutindeiBoardOutreachSendingDomain", {
    type: "String",
    default: "partners.siutindei.com",
    description:
      "SES From domain for Executive Board cold outreach. Owner must add DKIM CNAMEs, MAIL FROM MX+TXT and DMARC before sending succeeds.",
  });
  const outreachFromLocalPart = new cdk.CfnParameter(scope, "SiutindeiBoardOutreachFromLocalPart", {
    type: "String",
    default: "partnerships",
    description:
      "Local part of the outreach From address (partnerships@SiutindeiBoardOutreachSendingDomain).",
  });
  const publicSiteOrigins = new cdk.CfnParameter(scope, "PublicSiteOrigins", {
    type: "String",
    default: "https://lx-software.com,https://www.lx-software.com,https://siutindei.com,https://www.siutindei.com",
    description:
      "CSV of extra browser origins allowed on the HTTP API CORS list (admin origin is always included). Stack-wide; used by public newsletter subscribe and any other unauthenticated browser client.",
  });
  const publicApiBaseUrl = new cdk.CfnParameter(scope, "PublicApiBaseUrl", {
    type: "String",
    default: "",
    description:
      "Public base URL of this stack's HTTP API. Used today for board unsubscribe and newsletter confirm links. Leave blank to use the API endpoint CloudFormation assigns.",
  });
  const publicApiWritesEnabled = new cdk.CfnParameter(scope, "PublicApiWritesEnabled", {
    type: "String",
    default: "false",
    allowedValues: ["true", "false"],
    description:
      "Kill switch for public API-key PUT/POST/DELETE under /public/siu-tin-dei/board. Default false (fail-closed). Keys also need allowWrite on the APIKEY# row. Finance /public/* stays GET-only.",
  });
  const boardGitHubRepo = new cdk.CfnParameter(scope, "SiutindeiBoardGitHubRepo", {
    type: "String",
    default: "lx-software-ltd/siutindei",
    description: "owner/name of the repository the Executive Board reads.",
  });
  const boardMailDomain = new cdk.CfnParameter(scope, "SiutindeiBoardMailDomain", {
    type: "String",
    default: "siutindei.com",
    description:
      "Company mail domain the Executive Board reads. Every message to any mailbox at this domain is fanned out by a Cloudflare Email Worker to the board's SES inbound address and indexed (docs/architecture/executive-board.md §6.1).",
  });
  const boardMailSendingEnabled = new cdk.CfnParameter(
    scope,
    "SiutindeiBoardMailSendingEnabled",
    {
      type: "String",
      default: "false",
      allowedValues: ["true", "false"],
      description:
        "Set to true once SiutindeiBoardMailDomain is verified for sending in SES (DKIM CNAMEs, SPF include:amazonses.com, DMARC). Creates the SES identity and lets the board's mail tools send replies from that domain; false keeps mail read-only.",
    }
  );
  const boardChatModel = new cdk.CfnParameter(scope, "SiutindeiBoardChatModel", {
    type: "String",
    default: "openai/gpt-4.1-mini",
    description: "OpenRouter model slug for Executive Board chats (overridable in the admin settings).",
  });
  const boardMeetingModel = new cdk.CfnParameter(scope, "SiutindeiBoardMeetingModel", {
    type: "String",
    default: "openai/gpt-4.1-mini",
    description: "OpenRouter model slug for Executive Board stand-up meetings.",
  });
  const boardDeepDiveModel = new cdk.CfnParameter(scope, "SiutindeiBoardDeepDiveModel", {
    type: "String",
    default: "anthropic/claude-sonnet-4",
    description: "OpenRouter model slug for Executive Board deep-dive meetings.",
  });

  const inboundMailDomain = new cdk.CfnParameter(scope, "InboundMailDomain", {
    type: "String",
    default: "inbound.lx-software.com",
    description:
      "Domain for receiving statement mail (verify domain + MX to SES in this region before use).",
  });
  const statementParseNotifyEmail = new cdk.CfnParameter(
    scope,
    "StatementParseNotifyEmail",
    {
      type: "String",
      default: "",
      description:
        "Comma-separated addresses that receive an email when a statement parse job succeeds or fails. Empty disables notify. From is statements@InboundMailDomain (domain must be able to send in SES).",
    }
  );

  const evolvesproutsInvoiceRecipient = new cdk.CfnParameter(
    scope,
    "EvolvesproutsInboundInvoiceRecipient",
    {
      type: "String",
      default: "invoices@inbound.evolvesprouts.com",
      description:
        "SES recipient for Evolve Sprouts invoice automation (iCloud forwards invoices@evolvesprouts.com here).",
    }
  );
  const evolvesproutsInvoiceReceiptRoleName = new cdk.CfnParameter(
    scope,
    "EvolvesproutsInboundInvoiceReceiptRoleName",
    {
      type: "String",
      default: "evolvesprouts-InboundInvoiceReceiptRoleBA3C88C4-9AWbAAtiZBZS",
      description:
        "Physical IAM role name from the evolvesprouts stack. SES assumes it to write invoice mail to the ES assets bucket and publish SNS.",
    }
  );

  return {
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
  };
}

export type AdminParameters = ReturnType<typeof defineAdminParameters>;
