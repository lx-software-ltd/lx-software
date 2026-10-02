import * as cdk from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import type {
  HttpJwtAuthorizer,
  HttpLambdaAuthorizer,
} from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import type * as kms from "aws-cdk-lib/aws-kms";
import type * as lambda from "aws-cdk-lib/aws-lambda";
import { ROUTES } from "./admin-api-routes";

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
class SharedPermissionLambdaIntegration extends HttpLambdaIntegration {
  protected completeBind(_options: apigwv2.HttpRouteIntegrationBindOptions): void {
    // Intentionally empty: invoke permission is granted once for the whole API.
  }
}

export function defineAdminHttpApi(
  scope: cdk.Stack,
  deps: {
    readonly adminFn: lambda.Function;
    readonly jwtAuthorizer: HttpJwtAuthorizer;
    readonly publicApiKeyAuthorizer: HttpLambdaAuthorizer;
    readonly adminWebDomainName: cdk.CfnParameter;
    readonly publicSiteOrigins: cdk.CfnParameter;
    readonly publicApiBaseUrl: cdk.CfnParameter;
    readonly sharedEncryptionKey: kms.IKey;
  },
): apigwv2.HttpApi {
  const {
    adminFn,
    jwtAuthorizer,
    publicApiKeyAuthorizer,
    adminWebDomainName,
    publicSiteOrigins,
    publicApiBaseUrl,
    sharedEncryptionKey,
  } = deps;

  // AWS::ApiGatewayV2::Integration TimeoutInMillis must be 50–30000 ms in this
  // account/region; CDK defaults (~29s). Do not raise via L1 overrides.
  const integration = new SharedPermissionLambdaIntegration(
    "AdminIntegration",
    adminFn,
  );

  const adminOrigin = cdk.Fn.join("", [
    "https://",
    adminWebDomainName.valueAsString,
  ]);
  // A blank PublicSiteOrigins must not become an empty CORS origin (the
  // historical join always appended the parameter, so "" yielded a trailing
  // comma and an empty allow-list entry).
  const hasPublicSiteOrigins = new cdk.CfnCondition(scope, "HasPublicSiteOrigins", {
    expression: cdk.Fn.conditionNot(
      cdk.Fn.conditionEquals(publicSiteOrigins.valueAsString, ""),
    ),
  });
  const corsAllowOrigins = cdk.Fn.conditionIf(
    hasPublicSiteOrigins.logicalId,
    cdk.Fn.join(",", [adminOrigin, publicSiteOrigins.valueAsString]),
    adminOrigin,
  ).toString();

  const httpApi = new apigwv2.HttpApi(scope, "HttpApi", {
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
      allowOrigins: cdk.Fn.split(",", corsAllowOrigins),
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
    scope,
    principal: new iam.ServicePrincipal("apigateway.amazonaws.com"),
    sourceArn: httpApi.arnForExecuteApi(),
  });

  const accessLogGroup = new logs.LogGroup(scope, "HttpApiAccessLogs", {
    retention: logs.RetentionDays.ONE_MONTH,
    removalPolicy: cdk.RemovalPolicy.DESTROY,
    // CKV_AWS_158: encrypt at rest with the stack's shared CMK. The
    // CloudWatch Logs service principal is granted Encrypt*/Decrypt*
    // on the key in the stack-level policy above.
    encryptionKey: sharedEncryptionKey,
  });

  accessLogGroup.addToResourcePolicy(
    new iam.PolicyStatement({
      principals: [new iam.ServicePrincipal("apigateway.amazonaws.com")],
      actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
      resources: [`${accessLogGroup.logGroupArn}:*`],
    }),
  );

  const defaultStage = httpApi.defaultStage?.node.defaultChild as apigwv2.CfnStage;
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

  const hasPublicApiBaseUrl = new cdk.CfnCondition(scope, "HasPublicApiBaseUrl", {
    expression: cdk.Fn.conditionNot(
      cdk.Fn.conditionEquals(publicApiBaseUrl.valueAsString, ""),
    ),
  });
  adminFn.addEnvironment(
    "PUBLIC_API_BASE_URL",
    cdk.Fn.conditionIf(
      hasPublicApiBaseUrl.logicalId,
      publicApiBaseUrl.valueAsString,
      httpApi.apiEndpoint,
    ).toString(),
  );

  // One pass: each path stays its own route (board paths are not collapsed
  // into {proxy+}). The shared integration binds under the first route,
  // which must remain GET /health.
  const routeSettings: Record<
    string,
    { ThrottlingRateLimit: number; ThrottlingBurstLimit: number }
  > = {};
  for (const route of ROUTES) {
    const created = httpApi.addRoutes({
      path: route.path,
      methods: [...route.methods],
      integration,
      ...(route.auth === "jwt" ? { authorizer: jwtAuthorizer } : {}),
      ...(route.auth === "apiKey" ? { authorizer: publicApiKeyAuthorizer } : {}),
    });
    if (!route.throttle) {
      continue;
    }
    for (const method of route.methods) {
      routeSettings[`${method} ${route.path}`] = route.throttle;
    }
    // API Gateway V2 rejects RouteSettings keys until the Route exists.
    for (const createdRoute of created) {
      defaultStage.addResourceDependency(
        createdRoute.node.defaultChild as apigwv2.CfnRoute,
      );
    }
  }
  defaultStage.routeSettings = routeSettings;

  return httpApi;
}
