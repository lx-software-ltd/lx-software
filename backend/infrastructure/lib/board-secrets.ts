import * as cdk from "aws-cdk-lib";
import * as kms from "aws-cdk-lib/aws-kms";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import type { Construct } from "constructs";

/**
 * Siu Tin Dei connector secrets AdminApiFn reads, imported by name, plus the
 * importer credential placeholder.
 *
 * The seven `lxsoftware-admin-*` placeholder secrets (github read token, search,
 * meta token, meta app secret, app store, play, analytics) are not created.
 * AdminApiFn does not grant or reference them. They used RemovalPolicy.RETAIN,
 * so leaving them out of the template orphans the values instead of deleting them.
 */

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

export function defineBoardSecrets(scope: cdk.Stack, encryptionKey: kms.IKey) {
  const siutindeiBoardSecrets = boardImportedSecrets(scope, {
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
  /**
   * Places key (dummy, owner replaces) and HMAC link-signing key (CDK
   * generated 40 chars). Same history as the connector secrets: the first
   * autonomy deploy created them, RETAIN skipped delete on rollback, so a
   * fresh CREATE now fails with AlreadyExists. Import by name.
   */
  const googlePlacesKeySecret = secretsmanager.Secret.fromSecretNameV2(
    scope,
    "SiutindeiBoardGooglePlacesKey",
    "lxsoftware-admin-siutindei-board-google-places-key"
  );
  const boardLinkSigningSecret = secretsmanager.Secret.fromSecretNameV2(
    scope,
    "SiutindeiBoardLinkSigningKey",
    "lxsoftware-admin-siutindei-board-link-signing-key"
  );
  const boardImporterCredentialsSecret = boardPlaceholderSecret(scope, "SiutindeiBoardImporterCredentials", {
    secretName: "lxsoftware-admin-siutindei-board-importer-credentials",
    description:
      "Cognito username/password for the siutindei importer service user. Replace the dummy values in Secrets Manager.",
    encryptionKey,
    tenant: "siutindei",
    purpose: "board-importer",
    jsonTemplate: { username: "replace-me" },
    generateKey: "password",
  });
  const linkedinAppSecret = boardPlaceholderSecret(scope, "LxSoftwareLinkedinApp", {
    secretName: "lxsoftware-admin-linkedin-app",
    description:
      "LinkedIn app client id and client secret for the LX Software LinkedIn tab. Replace clientId and clientSecret in Secrets Manager.",
    encryptionKey,
    tenant: "lxsoftware",
    purpose: "linkedin-app",
    jsonTemplate: { clientId: "replace-me" },
    generateKey: "clientSecret",
  });
  return {
    siutindeiBoardSecrets,
    googlePlacesKeySecret,
    boardLinkSigningSecret,
    boardImporterCredentialsSecret,
    linkedinAppSecret,
  };
}

export type BoardSecrets = ReturnType<typeof defineBoardSecrets>;
