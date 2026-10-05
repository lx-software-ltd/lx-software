import * as cdk from "aws-cdk-lib";
import { ADMIN_WEB_HOSTNAME } from "./shared-contracts";
import { defineProductParameters } from "./admin-parameters-product";

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
        "ARN of the AWS Secrets Manager secret holding OpenRouter API keys. JSON object with named inference keys (statement-parser, executive-board, linkedin) plus management (Management API key) so sibling spend can be pulled. Sibling products keep their own named inference keys. Leave blank to disable those features.",
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
    ...defineProductParameters(scope),
  };
}

export type AdminParameters = ReturnType<typeof defineAdminParameters>;
