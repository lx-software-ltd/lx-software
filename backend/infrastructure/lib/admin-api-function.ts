import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import {
  HttpJwtAuthorizer,
  HttpLambdaAuthorizer,
  HttpLambdaResponseType,
} from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as logs from "aws-cdk-lib/aws-logs";
import type * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import type * as s3 from "aws-cdk-lib/aws-s3";
import type * as sqs from "aws-cdk-lib/aws-sqs";
import { AuthConstruct } from "./constructs/auth";
import { createPythonLambda } from "./constructs/python-lambda";
import { AuroraDataApiSetup } from "./constructs/siutindei-data-api";
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
  const region = cdk.Stack.of(scope).region;
  const issuer = `https://cognito-idp.${region}.amazonaws.com/${auth.userPool.userPoolId}`;

  /**
   * Contract: jwtAudience is the Cognito app client ID, which matches the
   * `aud` claim on **ID tokens** only. Access tokens use `client_id` instead
   * of `aud`, so the SPA must send ID tokens in Authorization (see
   * apps/admin_web/src/lib/apiAdminClient.ts). Switching to access tokens
   * requires a different authorizer configuration.
   */
  const jwtAuthorizer = new HttpJwtAuthorizer("cognito-jwt", issuer, {
    jwtAudience: [auth.userPoolClient.userPoolClientId],
  });

  /**
   * Public API key authorizer. Validates the `x-api-key` header against
   * scrypt key digests stored in the records table (`pk = APIKEY#<digest>`,
   * `sk = META`; minted via scripts/manage-public-api-keys.py). Guards
   * /public/* GET mirrors and (when allowWrite + PublicApiWritesEnabled)
   * board PUT/POST/DELETE. Cache is key + source IP, so this Lambda never
   * denies by HTTP method — the handler re-checks write_allowed.
   */
  const publicApiKeyAuthorizerFn = createPythonLambda(
    scope,
    "PublicApiKeyAuthorizerFn",
    {
      entryDir: path.join(__dirname, "..", "..", "lambda", "public_api_authorizer"),
      timeout: cdk.Duration.seconds(5),
      memorySize: 256,
      environmentEncryptionKey: sharedEncryptionKey,
      logEncryptionKey: sharedEncryptionKey,
      deadLetterQueue: lambdaDeadLetterQueue,
      environment: {
        RECORDS_TABLE_NAME: recordsTable.tableName,
      },
    }
  );
  lambdaDeadLetterQueue.grantSendMessages(publicApiKeyAuthorizerFn);

  // Narrow grant: the authorizer can only GetItem/UpdateItem on APIKEY#*
  // rows (lastUsedAt), never finance/asset/board records. The table uses
  // the shared CMK, so a matching kms:Decrypt grant is required.
  new iam.Policy(scope, "PublicApiKeyAuthorizerReadPolicy", {
    statements: [
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["dynamodb:GetItem", "dynamodb:UpdateItem"],
        resources: [recordsTable.tableArn],
        conditions: {
          "ForAllValues:StringLike": {
            "dynamodb:LeadingKeys": ["APIKEY#*"],
          },
        },
      }),
    ],
  }).attachToRole(publicApiKeyAuthorizerFn.role!);
  sharedEncryptionKey.grantDecrypt(publicApiKeyAuthorizerFn);

  const publicApiKeyAuthorizer = new HttpLambdaAuthorizer(
    "public-api-key",
    publicApiKeyAuthorizerFn,
    {
      responseTypes: [HttpLambdaResponseType.SIMPLE],
      // Cache key is header + client IP so a CIDR-bound key cannot be
      // reused from another address via the authorizer cache. Only
      // `$context.identity.sourceIp` is a supported HTTP API context
      // variable; a missing identity source makes API Gateway return 401
      // without invoking the authorizer.
      identitySource: [
        "$request.header.x-api-key",
        "$context.identity.sourceIp",
      ],
      // Revocation / CIDR changes take up to this TTL to propagate.
      resultsCacheTtl: cdk.Duration.seconds(60),
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

  // Cluster ARN only: CDK enables the HTTP Data API and applies
  // receivables.sql. Secret ARN is optional — blank resolves the
  // default siutindei master-secret name.
  const hasSiutindeiDataApi = new cdk.CfnCondition(scope, "HasSiutindeiDataApi", {
    expression: cdk.Fn.conditionNot(
      cdk.Fn.conditionEquals(siutindeiClusterArn.valueAsString, "")
    ),
  });
  const siutindeiDataApi = new AuroraDataApiSetup(scope, "SiutindeiDataApi", {
    clusterArn: siutindeiClusterArn.valueAsString,
    secretArn: siutindeiDbSecretArn.valueAsString,
    secretName: siutindeiDbSecretName.valueAsString,
    condition: hasSiutindeiDataApi,
    environmentEncryptionKey: sharedEncryptionKey,
    logEncryptionKey: sharedEncryptionKey,
    deadLetterQueue: lambdaDeadLetterQueue,
  });
  const hasEvolvesproutsDataApi = new cdk.CfnCondition(scope, "HasEvolvesproutsDataApi", {
    expression: cdk.Fn.conditionAnd(
      cdk.Fn.conditionNot(cdk.Fn.conditionEquals(evolvesproutsClusterArn.valueAsString, "")),
      cdk.Fn.conditionOr(
        cdk.Fn.conditionNot(cdk.Fn.conditionEquals(evolvesproutsDbSecretArn.valueAsString, "")),
        cdk.Fn.conditionNot(cdk.Fn.conditionEquals(evolvesproutsDbSecretName.valueAsString, ""))
      )
    ),
  });
  const evolvesproutsDataApi = new AuroraDataApiSetup(scope, "EvolvesproutsDataApi", {
    clusterArn: evolvesproutsClusterArn.valueAsString,
    secretArn: evolvesproutsDbSecretArn.valueAsString,
    secretName: evolvesproutsDbSecretName.valueAsString,
    databaseName: "evolvesprouts",
    applySql: false,
    scheduleName: "lxsoftware-admin-evolvesprouts-data-api-ensure",
    scheduleDescription:
      "Re-enable the Evolve Sprouts Aurora HTTP Data API. This stack does not apply SQL there.",
    scheduleInput: { internal: "data_api_ensure", applySql: "false" },
    httpEndpointPhysicalId: "evolvesprouts-aurora-http-endpoint",
    condition: hasEvolvesproutsDataApi,
    environmentEncryptionKey: sharedEncryptionKey,
    logEncryptionKey: sharedEncryptionKey,
    deadLetterQueue: lambdaDeadLetterQueue,
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
      assetMaxBytes: String(20 * 1024 * 1024),
      openrouterApiKeySecretArn: openRouterApiKeySecretArn.valueAsString,
      openrouterModel: openRouterModel.valueAsString,
      openrouterPdfEngine: openRouterPdfEngine.valueAsString,
      openrouterTimeoutSeconds: openRouterHttpTimeoutSeconds,
      parseJobStaleSeconds: parseJobStaleSeconds,
      parseJobStuckSeconds: parseJobStuckSeconds,
      parseJobTtlSeconds: String(PARSE_TIMEOUTS.parseJobTtlSeconds),
      enableBankingAppId: enableBankingAppId.valueAsString,
      enableBankingKmsKeyId: enableBankingSigningKey.keyId,
      githubReadTokenSecretArn: siutindeiBoardSecrets.github.secretArn,
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
      boardImporterCredentialsSecretArn: boardImporterCredentialsSecret.secretArn,
      publicApiWritesEnabled: publicApiWritesEnabled.valueAsString,
      outreachSendingDomain: outreachSendingDomain.valueAsString,
      outreachFromLocalPart: outreachFromLocalPart.valueAsString,
      newsletterConfigSet: "lxsoftware-admin-siutindei-newsletter",
      newsletterFromLocalPart: "news",
      searchApiKeySecretArn: siutindeiBoardSecrets.search.secretArn,
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
      evolvesproutsDbName: "evolvesprouts",
      metaBoardTokenSecretArn: siutindeiBoardSecrets.metaToken.secretArn,
      metaAppSecretSecretArn: siutindeiBoardSecrets.metaAppSecret.secretArn,
      metaVerifyToken: metaVerifyToken.valueAsString,
      metaPageId: metaPageId.valueAsString,
      metaIgUserId: metaIgUserId.valueAsString,
      metaWaPhoneNumberId: metaWaPhoneNumberId.valueAsString,
      metaWabaId: metaWabaId.valueAsString,
      metaAdAccountId: metaAdAccountId.valueAsString,
      appStoreConnectKeySecretArn: siutindeiBoardSecrets.appStore.secretArn,
      googlePlayServiceAccountSecretArn: siutindeiBoardSecrets.play.secretArn,
      appStoreConnectAppId: appStoreConnectAppId.valueAsString,
      ascVendorNumber: appStoreConnectVendorNumber.valueAsString,
      googlePlayPackageName: googlePlayPackageName.valueAsString,
      googleAnalyticsServiceAccountSecretArn: siutindeiBoardSecrets.analytics.secretArn,
      googlePlacesKeySecretArn: googlePlacesKeySecret.secretArn,
      boardLinkSigningSecretArn: boardLinkSigningSecret.secretArn,
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

  // Term patterns, not JSON patterns: the Python runtime prefixes each
  // line with "[LEVEL]\ttimestamp\trequest-id\t", so the event is not a
  // JSON document and `{ $.tag = ... }` would never match.
  new logs.MetricFilter(scope, "PublicApiKeyDeniedFilter", {
    logGroup: publicApiKeyAuthorizerFn.logGroup,
    filterPattern: logs.FilterPattern.allTerms("public_api_key_denied"),
    metricNamespace: "lxsoftware/public-api",
    metricName: "ApiKeyDenied",
    metricValue: "1",
  });
  new cloudwatch.Alarm(scope, "PublicApiKeyDeniedAlarm", {
    metric: new cloudwatch.Metric({
      namespace: "lxsoftware/public-api",
      metricName: "ApiKeyDenied",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    }),
    threshold: 20,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    alarmDescription: "Burst of denied public API key attempts.",
  });
  new logs.MetricFilter(scope, "PublicApiBoardFullFilter", {
    logGroup: adminFn.logGroup,
    filterPattern: logs.FilterPattern.allTerms(
      "public_api_access",
      "siutindei-board-full"
    ),
    metricNamespace: "lxsoftware/public-api",
    metricName: "BoardFullAccess",
    metricValue: "1",
  });
  new logs.MetricFilter(scope, "PublicApiWriteFilter", {
    logGroup: adminFn.logGroup,
    filterPattern: logs.FilterPattern.allTerms("public_api_write"),
    metricNamespace: "lxsoftware/public-api",
    metricName: "PublicApiWrite",
    metricValue: "1",
  });
  new cloudwatch.Alarm(scope, "PublicApiWriteAlarm", {
    metric: new cloudwatch.Metric({
      namespace: "lxsoftware/public-api",
      metricName: "PublicApiWrite",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    }),
    threshold: 20,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    alarmDescription: "Burst of public API-key board writes.",
  });
  new cloudwatch.Alarm(scope, "PublicApiBoardFullAlarm", {
    metric: new cloudwatch.Metric({
      namespace: "lxsoftware/public-api",
      metricName: "BoardFullAccess",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    }),
    threshold: 30,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    alarmDescription: "Jump in siutindei-board-full public API reads.",
  });
  // Replaces RecursiveInvocationsDropped after RecursiveLoop Allow.
  // Observed 5-min peak on 2026-09-14/15 was 145 (evening standup). The
  // name includes "siutindei" so hourly board_cache_refresh / aws_list_alarms
  // surfaces a new ALARM as an architect/CTO task.
  new cloudwatch.Alarm(scope, "AdminApiInvocationsAlarm", {
    alarmName: "lxsoftware-admin-siutindei-admin-api-invocations",
    metric: adminFn.metricInvocations({
      period: cdk.Duration.minutes(5),
      statistic: "Sum",
    }),
    threshold: 250,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    alarmDescription:
      "AdminApiFn invoke burst (tight self-invoke runaway). 5-min peak before Allow was 145.",
  });

  // Allow async-invocation DLQ writes from this function.
  lambdaDeadLetterQueue.grantSendMessages(adminFn);

  recordsTable.grantReadWriteData(adminFn);
  assetsBucket.grantReadWrite(adminFn);

  // Grant SecretsManager:GetSecretValue only when an ARN is provided.
  // We can't conditionally call grantRead() from a CfnParameter, so we
  // attach a narrow IAM policy that resolves to the parameter value at
  // deploy time. When the ARN is blank, the resource list collapses to
  // an empty string and the action is effectively a no-op.
  const openRouterSecretArnValue = openRouterApiKeySecretArn.valueAsString;
  const hasOpenRouterSecret = new cdk.CfnCondition(
    scope,
    "HasOpenRouterSecret",
    {
      expression: cdk.Fn.conditionNot(
        cdk.Fn.conditionEquals(openRouterSecretArnValue, "")
      ),
    }
  );
  const openRouterSecretPolicy = new iam.Policy(scope, "AdminOpenRouterSecretPolicy", {
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
  boardImporterCredentialsSecret.grantRead(adminFn);
  // AdminInitiateAuth is scoped to SiutindeiUserPoolId. The parameter
  // defaults to "" (ARN …:userpool/), so skip the policy until a pool id
  // is set — same pattern as HasOpenRouterSecret.
  const hasSiutindeiUserPool = new cdk.CfnCondition(scope, "HasSiutindeiUserPool", {
    expression: cdk.Fn.conditionNot(cdk.Fn.conditionEquals(siutindeiUserPoolId.valueAsString, "")),
  });
  const importerAuthPolicy = new iam.Policy(scope, "SiutindeiBoardImporterAuthPolicy", {
    statements: [
      new iam.PolicyStatement({
        sid: "SiutindeiImporterAdminInitiateAuth",
        actions: ["cognito-idp:AdminInitiateAuth"],
        resources: [
          scope.formatArn({
            service: "cognito-idp",
            resource: "userpool",
            resourceName: siutindeiUserPoolId.valueAsString,
            arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
          }),
        ],
      }),
    ],
  });
  importerAuthPolicy.attachToRole(adminFn.role!);
  (importerAuthPolicy.node.defaultChild as iam.CfnPolicy).cfnOptions.condition = hasSiutindeiUserPool;

  // Executive Board aws + security read tools (plan §8). Each statement is
  // scoped as tightly as the IAM action allows (see the Service
  // Authorization Reference); the handler additionally filters CloudWatch
  // results to the siutindei stacks in code.
  new iam.Policy(scope, "SiutindeiBoardAwsReadPolicy", {
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
        resources: [auth.userPool.userPoolArn],
      }),
      // GetFindings is authorised against the regional `hub/default`
      // resource; the handler uses the Lambda's own region.
      new iam.PolicyStatement({
        sid: "SecurityHubGetFindings",
        actions: ["securityhub:GetFindings"],
        resources: [
          cdk.Stack.of(scope).formatArn({
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
          cdk.Stack.of(scope).formatArn({
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

  const dataApiPolicy = new iam.Policy(scope, "AdminSiutindeiDataApiPolicy", {
    statements: [
      new iam.PolicyStatement({
        actions: ["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
        resources: [siutindeiClusterArn.valueAsString],
      }),
      new iam.PolicyStatement({
        actions: ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
        resources: [
          siutindeiDataApi.resolvedSecretArn,
          scope.formatArn({
            service: "secretsmanager",
            resource: "secret",
            resourceName: `${siutindeiDbSecretName.valueAsString}*`,
            arnFormat: cdk.ArnFormat.COLON_RESOURCE_NAME,
          }),
        ],
      }),
      new iam.PolicyStatement({
        actions: ["kms:Decrypt", "kms:DescribeKey"],
        resources: ["*"],
        conditions: {
          StringEquals: {
            "kms:ViaService": `secretsmanager.${scope.region}.amazonaws.com`,
          },
        },
      }),
    ],
  });
  dataApiPolicy.attachToRole(adminFn.role!);
  (dataApiPolicy.node.defaultChild as iam.CfnPolicy).cfnOptions.condition = hasSiutindeiDataApi;

  const evolvesproutsDataApiPolicy = new iam.Policy(scope, "AdminEvolvesproutsDataApiPolicy", {
    statements: [
      new iam.PolicyStatement({
        actions: ["rds-data:ExecuteStatement"],
        resources: [evolvesproutsClusterArn.valueAsString],
      }),
      new iam.PolicyStatement({
        actions: ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
        resources: [evolvesproutsDataApi.resolvedSecretArn],
      }),
      new iam.PolicyStatement({
        actions: ["kms:Decrypt", "kms:DescribeKey"],
        resources: ["*"],
        conditions: {
          StringEquals: {
            "kms:ViaService": `secretsmanager.${scope.region}.amazonaws.com`,
          },
        },
      }),
    ],
  });
  evolvesproutsDataApiPolicy.attachToRole(adminFn.role!);
  (evolvesproutsDataApiPolicy.node.defaultChild as iam.CfnPolicy).cfnOptions.condition =
    hasEvolvesproutsDataApi;

  return {
    adminFn,
    jwtAuthorizer,
    publicApiKeyAuthorizer,
    enableBankingSigningKey,
    openRouterSecretPolicy,
    outreach,
  };
}
