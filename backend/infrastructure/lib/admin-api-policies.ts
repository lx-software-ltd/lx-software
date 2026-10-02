import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import type * as lambda from "aws-cdk-lib/aws-lambda";
import type * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import type { AuthConstruct } from "./constructs/auth";
import type { AuroraDataApiSetup } from "./constructs/siutindei-data-api";

type BoardConnectorSecrets = {
  readonly github: secretsmanager.ISecret;
  readonly search: secretsmanager.ISecret;
  readonly metaToken: secretsmanager.ISecret;
  readonly metaAppSecret: secretsmanager.ISecret;
  readonly appStore: secretsmanager.ISecret;
  readonly play: secretsmanager.ISecret;
  readonly analytics: secretsmanager.ISecret;
};

/** IAM grants for AdminApiFn. Policy construct ids are unchanged. */
export function grantAdminApiPolicies(
  scope: cdk.Stack,
  input: {
    readonly adminFn: lambda.Function;
    readonly openRouterApiKeySecretArn: cdk.CfnParameter;
    readonly siutindeiBoardSecrets: BoardConnectorSecrets;
    readonly googlePlacesKeySecret: secretsmanager.ISecret;
    readonly boardLinkSigningSecret: secretsmanager.ISecret;
    readonly boardImporterCredentialsSecret: secretsmanager.ISecret;
    readonly siutindeiUserPoolId: cdk.CfnParameter;
    readonly auth: AuthConstruct;
    readonly siutindeiClusterArn: cdk.CfnParameter;
    readonly siutindeiDataApi: AuroraDataApiSetup;
    readonly siutindeiDbSecretName: cdk.CfnParameter;
    readonly hasSiutindeiDataApi: cdk.CfnCondition;
    readonly evolvesproutsClusterArn: cdk.CfnParameter;
    readonly evolvesproutsDataApi: AuroraDataApiSetup;
    readonly hasEvolvesproutsDataApi: cdk.CfnCondition;
  },
): iam.Policy {
  const {
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
  } = input;
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

  return openRouterSecretPolicy;
}
