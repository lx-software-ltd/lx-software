import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import {
  HttpJwtAuthorizer,
  HttpLambdaAuthorizer,
  HttpLambdaResponseType,
} from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import * as iam from "aws-cdk-lib/aws-iam";
import type * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import type * as kms from "aws-cdk-lib/aws-kms";
import type * as lambda from "aws-cdk-lib/aws-lambda";
import type * as sqs from "aws-cdk-lib/aws-sqs";
import type { AuthConstruct } from "./constructs/auth";
import { createPythonLambda } from "./constructs/python-lambda";

/** Cognito JWT authorizer and the public API key Lambda authorizer. */
export function defineAdminAuthorizers(
  scope: cdk.Stack,
  input: {
    readonly auth: AuthConstruct;
    readonly recordsTable: dynamodb.Table;
    readonly sharedEncryptionKey: kms.IKey;
    readonly lambdaDeadLetterQueue: sqs.Queue;
  },
) {
  const { auth, recordsTable, sharedEncryptionKey, lambdaDeadLetterQueue } = input;
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
  return { jwtAuthorizer, publicApiKeyAuthorizer, publicApiKeyAuthorizerFn };
}
