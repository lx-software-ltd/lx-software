import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import {
  HttpJwtAuthorizer,
  HttpLambdaAuthorizer,
} from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as lambda from "aws-cdk-lib/aws-lambda";
import type * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import type * as s3 from "aws-cdk-lib/aws-s3";
import type * as sqs from "aws-cdk-lib/aws-sqs";
import { AuthConstruct } from "./constructs/auth";
import { createPythonLambda } from "./constructs/python-lambda";
import { defineAdminAuthorizers } from "./admin-api-authorizers";
import { defineAdminApiAlarms } from "./admin-api-alarms";
import { defineProductDataApis } from "./admin-api-data";
import { grantAdminApiPolicies } from "./admin-api-policies";
import { PARSE_TIMEOUTS } from "./shared-contracts";
import type { AdminParameters } from "./admin-parameters";
import { buildAdminEnv } from "./admin-api-env";
import { defineBoardSecrets } from "./board-secrets";
import { defineBoardSchedules } from "./board-schedules";
import { defineOutreachEvents, type OutreachEvents } from "./outreach-events";

export interface AdminApiResources {
  readonly adminFn: lambda.Function;
  readonly jwtAuthorizer: HttpJwtAuthorizer;
  readonly publicApiKeyAuthorizer: HttpLambdaAuthorizer;
  readonly enableBankingSigningKey: kms.Key;
  readonly openRouterSecretPolicy: iam.Policy;
  readonly outreach: OutreachEvents;
}

export function defineAdminApiFunction(
  scope: cdk.Stack,
  deps: {
    readonly params: AdminParameters;
    readonly auth: AuthConstruct;
    readonly recordsTable: dynamodb.Table;
    readonly auditLogTable: dynamodb.Table;
    readonly assetsBucket: s3.Bucket;
    readonly sharedEncryptionKey: kms.IKey;
    readonly lambdaDeadLetterQueue: sqs.Queue;
  },
): AdminApiResources {
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
    auth,
    recordsTable,
    auditLogTable,
    assetsBucket,
    sharedEncryptionKey,
    lambdaDeadLetterQueue,
  } = deps;
  const { jwtAuthorizer, publicApiKeyAuthorizer, publicApiKeyAuthorizerFn } = defineAdminAuthorizers(
    scope,
    { auth, recordsTable, sharedEncryptionKey, lambdaDeadLetterQueue },
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

  const {
    siutindeiBoardSecrets,
    googlePlacesKeySecret,
    boardLinkSigningSecret,
    boardImporterCredentialsSecret,
  } = defineBoardSecrets(scope, sharedEncryptionKey);

  /**
   * Asymmetric RSA key that signs the Enable Banking RS256 JWTs. The
   * private key never leaves KMS; the admin Lambda calls kms:Sign per
   * token (tokens are cached for ~1h in the Lambda, so call volume is
   * negligible). RETAIN: losing the key would orphan the Enable Banking
   * application registration. Asymmetric KMS keys do not support
   * automatic rotation.
   */
  const enableBankingSigningKey = new kms.Key(scope, "EnableBankingSigningKey", {
    alias: "lxsoftware-admin/enable-banking",
    description:
      "RSA signing key for Enable Banking API JWTs (bank account sync).",
    keySpec: kms.KeySpec.RSA_2048,
    keyUsage: kms.KeyUsage.SIGN_VERIFY,
    removalPolicy: cdk.RemovalPolicy.RETAIN,
  });

  const {
    hasSiutindeiDataApi,
    siutindeiDataApi,
    hasEvolvesproutsDataApi,
    evolvesproutsDataApi,
  } = defineProductDataApis(scope, {
    siutindeiClusterArn,
    siutindeiDbSecretArn,
    siutindeiDbSecretName,
    evolvesproutsClusterArn,
    evolvesproutsDbSecretArn,
    evolvesproutsDbSecretName,
    sharedEncryptionKey,
    lambdaDeadLetterQueue,
  });


  // Asset hash includes backend/lambda/admin. Deploy Backend must watch that
  // tree (see .github/workflows/deploy-backend.yml) so a Lambda-only merge
  // still replaces AdminApiFn — otherwise the SPA can call routes that 404.
  const adminFn = createPythonLambda(scope, "AdminApiFn", {
    entryDir: path.join(__dirname, "..", "..", "lambda", "admin"),
    timeout: adminStatementParseLambdaTimeout,
    memorySize: 1536,
    // Staff steps, meeting phases, chat/parse workers and intel crawl
    // continue via Event invoke of this same function. Lambda's default
    // Terminate drops the chain after ~16 hops and sends
    // AWS_LAMBDA_RUNAWAY_TERMINATION_NOTIFICATION. Application caps
    // (maxStepsPerTask, meeting phases, crawl pages) still bound work.
    recursiveLoop: lambda.RecursiveLoop.ALLOW,
    environmentEncryptionKey: sharedEncryptionKey,
    logEncryptionKey: sharedEncryptionKey,
    deadLetterQueue: lambdaDeadLetterQueue,
    environment: buildAdminEnv({
      recordsTableName: recordsTable.tableName,
      auditLogTableName: auditLogTable.tableName,
      assetsBucketName: assetsBucket.bucketName,
      openrouterApiKeySecretArn: openRouterApiKeySecretArn.valueAsString,
      openrouterModel: openRouterModel.valueAsString,
      openrouterPdfEngine: openRouterPdfEngine.valueAsString,
      openrouterTimeoutSeconds: openRouterHttpTimeoutSeconds,
      parseJobStaleSeconds: parseJobStaleSeconds,
      parseJobStuckSeconds: parseJobStuckSeconds,
      enableBankingAppId: enableBankingAppId.valueAsString,
      enableBankingKmsKeyId: enableBankingSigningKey.keyId,
      githubReadTokenSecretArn: siutindeiBoardSecrets.github.secretName,
      boardGithubRepo: boardGitHubRepo.valueAsString,
      boardChatModel: boardChatModel.valueAsString,
      boardMeetingModel: boardMeetingModel.valueAsString,
      boardDeepDiveModel: boardDeepDiveModel.valueAsString,
      boardToolsEnabled: boardToolsEnabled.valueAsString,
      boardStaffEnabled: boardStaffEnabled.valueAsString,
      boardCatalogImportEnabled: boardCatalogImportEnabled.valueAsString,
      siutindeiAdminApiBaseUrl: siutindeiAdminApiBaseUrl.valueAsString,
      siutindeiUserPoolId: siutindeiUserPoolId.valueAsString,
      boardImporterClientId: boardImporterClientId.valueAsString,
      boardCatalogManagerId: boardCatalogManagerId.valueAsString,
      // Literal name: Secret.secretName parses the ARN and stops at the first hyphen.
      boardImporterCredentialsSecretArn: "lxsoftware-admin-siutindei-board-importer-credentials",
      publicApiWritesEnabled: publicApiWritesEnabled.valueAsString,
      outreachSendingDomain: outreachSendingDomain.valueAsString,
      outreachFromLocalPart: outreachFromLocalPart.valueAsString,
      searchApiKeySecretArn: siutindeiBoardSecrets.search.secretName,
      boardAwsStackPrefix: boardAwsStackPrefix.valueAsString,
      boardAwsLambdaNames: boardAwsLambdaNames.valueAsString,
      userPoolId: auth.userPool.userPoolId,
      siutindeiClusterArn: siutindeiClusterArn.valueAsString,
      siutindeiDbSecretArn: cdk.Fn.conditionIf(
        hasSiutindeiDataApi.logicalId,
        siutindeiDataApi.resolvedSecretArn,
        ""
      ).toString(),
      evolvesproutsClusterArn: evolvesproutsClusterArn.valueAsString,
      evolvesproutsDbSecretArn: cdk.Fn.conditionIf(
        hasEvolvesproutsDataApi.logicalId,
        evolvesproutsDataApi.resolvedSecretArn,
        ""
      ).toString(),
      metaBoardTokenSecretArn: siutindeiBoardSecrets.metaToken.secretName,
      metaAppSecretSecretArn: siutindeiBoardSecrets.metaAppSecret.secretName,
      metaVerifyToken: metaVerifyToken.valueAsString,
      metaPageId: metaPageId.valueAsString,
      metaIgUserId: metaIgUserId.valueAsString,
      metaWaPhoneNumberId: metaWaPhoneNumberId.valueAsString,
      metaWabaId: metaWabaId.valueAsString,
      metaAdAccountId: metaAdAccountId.valueAsString,
      appStoreConnectKeySecretArn: siutindeiBoardSecrets.appStore.secretName,
      googlePlayServiceAccountSecretArn: siutindeiBoardSecrets.play.secretName,
      appStoreConnectAppId: appStoreConnectAppId.valueAsString,
      ascVendorNumber: appStoreConnectVendorNumber.valueAsString,
      googlePlayPackageName: googlePlayPackageName.valueAsString,
      googleAnalyticsServiceAccountSecretArn: siutindeiBoardSecrets.analytics.secretName,
      googlePlacesKeySecretArn: googlePlacesKeySecret.secretName,
      boardLinkSigningSecretArn: boardLinkSigningSecret.secretName,
      ga4PropertyIds: ga4PropertyIds.valueAsString,
      gtmContainers: gtmContainers.valueAsString,
      boardMailSendingEnabled: boardMailSendingEnabled.valueAsString,
      adminWebOrigin: cdk.Fn.join("", [
        "https://",
        adminWebDomainName.valueAsString,
      ]),
    }),
  });

  enableBankingSigningKey.grant(adminFn, "kms:Sign", "kms:GetPublicKey");

  defineBoardSchedules(scope, adminFn, hasEvolvesproutsDataApi);
  const outreach = defineOutreachEvents(
    scope,
    adminFn,
    sharedEncryptionKey,
    outreachSendingDomain,
  );
  // Self-invoke worker name: handler falls back to the Lambda runtime's
  // built-in `AWS_LAMBDA_FUNCTION_NAME` env var when `PARSE_WORKER_FUNCTION_NAME`
  // is unset, so we deliberately do NOT add a self-referencing env var here
  // (`addEnvironment("PARSE_WORKER_FUNCTION_NAME", adminFn.functionName)` would
  // make AdminApiFn depend on itself via `Ref`, which CloudFormation rejects
  // as a circular dependency).

  new lambda.EventInvokeConfig(scope, "AdminApiAsyncInvoke", {
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
  // attached only to this Lambda, whose code is the sole consumer. The wildcard exists to avoid a circular policy/function reference; setting functionName on AdminApiFn would replace the function.
  const selfInvokeArn = cdk.Stack.of(scope).formatArn({
    service: "lambda",
    resource: "function",
    resourceName: "*",
    arnFormat: cdk.ArnFormat.COLON_RESOURCE_NAME,
  });
  new iam.Policy(scope, "AdminApiFnSelfInvokePolicy", {
    statements: [
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["lambda:InvokeFunction"],
        resources: [selfInvokeArn],
      }),
    ],
  }).attachToRole(adminFn.role!);

  // Identity-based invoke only (do not grantInvoke on AdminApiFn — that
  // adds a resource-based statement and the function policy is size-capped).
  publicApiKeyAuthorizerFn.addEnvironment(
    "ADMIN_API_FUNCTION_NAME",
    adminFn.functionName
  );
  new iam.Policy(scope, "PublicApiKeyAuthorizerInvokeAdminPolicy", {
    statements: [
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["lambda:InvokeFunction"],
        resources: [adminFn.functionArn],
      }),
    ],
  }).attachToRole(publicApiKeyAuthorizerFn.role!);

  defineAdminApiAlarms(scope, { adminFn, publicApiKeyAuthorizerFn });


  // Allow async-invocation DLQ writes from this function.
  lambdaDeadLetterQueue.grantSendMessages(adminFn);

  recordsTable.grantReadWriteData(adminFn);
  assetsBucket.grantReadWrite(adminFn);

  const openRouterSecretPolicy = grantAdminApiPolicies(scope, {
    adminFn,
    openRouterApiKeySecretArn,
    siutindeiBoardSecrets,
    googlePlacesKeySecret,
    boardLinkSigningSecret,
    boardImporterCredentialsSecret,
    siutindeiUserPoolId,
    auth,
    siutindeiClusterArn,
    siutindeiDataApi,
    siutindeiDbSecretName,
    hasSiutindeiDataApi,
    evolvesproutsClusterArn,
    evolvesproutsDataApi,
    hasEvolvesproutsDataApi,
  });

  return {
    adminFn,
    jwtAuthorizer,
    publicApiKeyAuthorizer,
    enableBankingSigningKey,
    openRouterSecretPolicy,
    outreach,
  };
}
