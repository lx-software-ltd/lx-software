import * as cdk from "aws-cdk-lib";
import type * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import type * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import type * as kms from "aws-cdk-lib/aws-kms";
import type * as s3 from "aws-cdk-lib/aws-s3";
import type * as sqs from "aws-cdk-lib/aws-sqs";
import type { Construct } from "constructs";
import { defineAdminHttpApi } from "./admin-http-api";
import { defineAdminOutputs } from "./admin-outputs";
import { defineAdminApiFunction } from "./admin-api-function";
import { defineAdminBuckets, defineAdminTables, defineSharedEncryption } from "./admin-data";
import { defineAdminParameters } from "./admin-parameters";
import { defineInboundMail } from "./inbound-mail";
import { AuthConstruct } from "./constructs/auth";

/**
 * Consolidated admin backend stack: Cognito user pool (with Pre Token
 * Generation Lambda + Google IdP), DynamoDB tables, private uploads
 * bucket (with its own S3 access logs bucket), and the HTTP API plus
 * the admin Lambda that consumes them.
 *
 * All physical names use the `lxsoftware-admin-*` prefix.
 *
 * Resources are created by stack-scoped functions (the stack is `scope`).
 * Logical IDs stay on the path from this stack; do not wrap existing
 * resources in a nested Construct.
 *
 * Feature flags such as `@aws-cdk/aws-iam:minimizePolicies` stay off.
 * Turning them on changes synthesized IAM and logical IDs and needs a
 * production `cdk diff` before it is safe.
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

    const params = defineAdminParameters(this);
    const encryption = defineSharedEncryption(this);
    this.sharedEncryptionKey = encryption.sharedEncryptionKey;
    this.lambdaDeadLetterQueue = encryption.lambdaDeadLetterQueue;

    this.auth = new AuthConstruct(this, "Auth", {
      adminWebDomainParameter: params.adminWebDomainName,
      googleClientIdParameter: params.googleClientId,
      googleClientSecretParameter: params.googleClientSecret,
      cognitoDomainPrefixParameter: params.cognitoDomainPrefix,
      cognitoCustomDomainNameParameter: params.cognitoCustomDomainName,
      cognitoCustomDomainCertificateArnParameter: params.cognitoCustomDomainCertificateArn,
      adminBootstrapEmailParameter: params.adminBootstrapEmail,
      adminBootstrapTempPasswordParameter: params.adminBootstrapTempPassword,
      adminFederatedEmailAllowlistParameter: params.adminFederatedEmailAllowlist,
      sharedEncryptionKey: this.sharedEncryptionKey,
      sharedDeadLetterQueue: this.lambdaDeadLetterQueue,
    });

    const tables = defineAdminTables(this, this.sharedEncryptionKey);
    this.recordsTable = tables.recordsTable;
    this.auditLogTable = tables.auditLogTable;

    const buckets = defineAdminBuckets(this, params.adminWebDomainName);
    this.assetsBucket = buckets.assetsBucket;
    this.assetsAccessLogsBucket = buckets.assetsAccessLogsBucket;

    const api = defineAdminApiFunction(this, {
      params,
      auth: this.auth,
      recordsTable: this.recordsTable,
      auditLogTable: this.auditLogTable,
      assetsBucket: this.assetsBucket,
      sharedEncryptionKey: this.sharedEncryptionKey,
      lambdaDeadLetterQueue: this.lambdaDeadLetterQueue,
    });

    const mail = defineInboundMail(this, {
      params,
      recordsTable: this.recordsTable,
      auditLogTable: this.auditLogTable,
      assetsBucket: this.assetsBucket,
      sharedEncryptionKey: this.sharedEncryptionKey,
      lambdaDeadLetterQueue: this.lambdaDeadLetterQueue,
      adminFn: api.adminFn,
      openRouterSecretPolicy: api.openRouterSecretPolicy,
    });

    this.httpApi = defineAdminHttpApi(this, {
      adminFn: api.adminFn,
      jwtAuthorizer: api.jwtAuthorizer,
      publicApiKeyAuthorizer: api.publicApiKeyAuthorizer,
      adminWebDomainName: params.adminWebDomainName,
      publicSiteOrigins: params.publicSiteOrigins,
      publicApiBaseUrl: params.publicApiBaseUrl,
      sharedEncryptionKey: this.sharedEncryptionKey,
    });

    defineAdminOutputs(this, {
      auth: this.auth,
      recordsTable: this.recordsTable,
      auditLogTable: this.auditLogTable,
      assetsBucket: this.assetsBucket,
      httpApi: this.httpApi,
      inboundMailDomain: params.inboundMailDomain,
      evolvesproutsInvoiceRecipient: params.evolvesproutsInvoiceRecipient,
      enableBankingSigningKey: api.enableBankingSigningKey,
      outreachSendingIdentity: api.outreach.outreachSendingIdentity,
      ...mail,
    });
  }
}
