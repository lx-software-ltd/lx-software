import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";

/**
 * Shared CMK, DLQ, DynamoDB tables, and the private uploads bucket.
 * Construct ids match the historical stack so tables and buckets are not replaced.
 */
export function defineSharedEncryption(scope: cdk.Stack) {
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
  const sharedEncryptionKey = new kms.Key(scope, "SharedEncryptionKey", {
    alias: "lxsoftware-admin/shared",
    description:
      "Shared CMK for Lambda env vars, CloudWatch logs, DynamoDB, and SQS DLQ in the lxsoftware admin stack.",
    enableKeyRotation: true,
    removalPolicy: cdk.RemovalPolicy.RETAIN,
  });

  const region = cdk.Stack.of(scope).region;
  const accountId = cdk.Stack.of(scope).account;
  sharedEncryptionKey.addToResourcePolicy(
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

  const lambdaDeadLetterQueue = new sqs.Queue(scope, "LambdaDeadLetterQueue", {
    queueName: "lxsoftware-admin-lambda-dlq",
    encryption: sqs.QueueEncryption.KMS,
    encryptionMasterKey: sharedEncryptionKey,
    retentionPeriod: cdk.Duration.days(14),
  });
  return { sharedEncryptionKey, lambdaDeadLetterQueue };
}

export function defineAdminTables(scope: cdk.Stack, sharedEncryptionKey: kms.IKey) {
  // ------------------------------------------------------------------
  // 3. Data (DynamoDB tables)
  //
  // Both tables use the shared customer-managed KMS key (CKV_AWS_119).
  // KMS API calls are charged per request beyond the free tier (20k/mo),
  // but the admin-only workload stays well below that ceiling.
  // ------------------------------------------------------------------
  const recordsTable = new dynamodb.Table(scope, "RecordsTable", {
    tableName: "lxsoftware-admin-records",
    partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
    sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
    billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
    pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
    encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
    encryptionKey: sharedEncryptionKey,
    removalPolicy: cdk.RemovalPolicy.RETAIN,
    timeToLiveAttribute: "expiresAt",
  });

  recordsTable.addGlobalSecondaryIndex({
    indexName: "gsi1",
    partitionKey: { name: "gsi1pk", type: dynamodb.AttributeType.STRING },
    sortKey: { name: "gsi1sk", type: dynamodb.AttributeType.STRING },
    projectionType: dynamodb.ProjectionType.ALL,
  });


  const auditLogTable = new dynamodb.Table(scope, "AuditLogTable", {
    tableName: "lxsoftware-admin-audit-log",
    partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
    sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
    billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
    pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
    encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
    encryptionKey: sharedEncryptionKey,
    removalPolicy: cdk.RemovalPolicy.RETAIN,
  });
  return { recordsTable, auditLogTable };
}

export function defineAdminBuckets(scope: cdk.Stack, adminWebDomainName: cdk.CfnParameter) {
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

  const assetsAccessLogsBucket = new s3.Bucket(scope, "AssetsS3AccessLogsBucket", {
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
  const assetsBucket = new s3.Bucket(scope, "AssetsBucket", {
    bucketName: assetsBucketName,
    blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    encryption: s3.BucketEncryption.S3_MANAGED,
    enforceSSL: true,
    versioned: true,
    removalPolicy: cdk.RemovalPolicy.RETAIN,
    serverAccessLogsBucket: assetsAccessLogsBucket,
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
  return { assetsAccessLogsBucket, assetsBucket };
}
