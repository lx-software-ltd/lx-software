import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";

export class PublicWebsiteStack extends cdk.Stack {
  public readonly bucket: s3.IBucket;
  public readonly distribution: cloudfront.Distribution;
  public readonly accessLogsBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Common tags (Organization, Project, Environment, ManagedBy, Repository,
    // Stack, Component) are applied centrally in bin/app.ts.

    const domainName = new cdk.CfnParameter(this, "PublicWebsiteDomainName", {
      type: "String",
      description: "Custom domain for the public website (CloudFront alias).",
    });

    const certificateArn = new cdk.CfnParameter(
      this,
      "PublicWebsiteCertificateArn",
      {
        type: "String",
        description: "ACM certificate ARN for the public website domain.",
      }
    );

    // Bucket name: lxsoftware-public-www-{account}-{region} (49 chars)
    const bucketName = [
      "lxsoftware-public-www",
      cdk.Aws.ACCOUNT_ID,
      cdk.Aws.REGION,
    ].join("-");

    // S3 bucket for CloudFront access logs (CKV_AWS_86)
    // Bucket name: lxsoftware-public-www-logs-{account}-{region}
    const logsBucketName = [
      "lxsoftware-public-www-logs",
      cdk.Aws.ACCOUNT_ID,
      cdk.Aws.REGION,
    ].join("-");

    this.accessLogsBucket = new s3.Bucket(this, "CloudFrontAccessLogsBucket", {
      bucketName: logsBucketName,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true, // CKV_AWS_21: Enable versioning for the S3 bucket
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          id: "ExpireOldLogs",
          enabled: true,
          expiration: cdk.Duration.days(90),
        },
      ],
    });

    // Import existing bucket using attributes so we have the ARN for policy creation
    this.bucket = s3.Bucket.fromBucketAttributes(this, "PublicWebsiteBucket", {
      bucketName: bucketName,
      bucketArn: cdk.Arn.format({
        service: "s3",
        resource: bucketName,
        region: "",
        account: "",
      }, this),
    });

    const certificate = acm.Certificate.fromCertificateArn(
      this,
      "PublicWebsiteCertificate",
      certificateArn.valueAsString
    );

    // Imported buckets cannot receive CDK's automatic OAC bucket policy statement; we grant
    // CloudFront read access explicitly below. Acknowledge the library warning so synth stays clean.
    cdk.Annotations.of(this).acknowledgeWarning(
      "@aws-cdk/aws-cloudfront-origins:updateImportedBucketPolicyOac",
      "OAC access for the imported public website bucket is granted via PublicWebsiteBucketPolicy.",
    );

    // Use Origin Access Control (OAC) - the recommended approach for S3 origins
    // OAC is more secure than the legacy OAI and supports additional features
    const origin = origins.S3BucketOrigin.withOriginAccessControl(this.bucket);

    const csp = [
      "default-src 'self'",
      "script-src 'self'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: https://media.lx-software.com",
      "media-src 'self' https://media.lx-software.com",
      "font-src 'self'",
      "connect-src 'self'",
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'",
    ].join("; ");

    const securityHeaders = new cloudfront.ResponseHeadersPolicy(
      this,
      "PublicWebsiteSecurityHeaders",
      {
        responseHeadersPolicyName: "lxsoftware-public-www-security-headers",
        securityHeadersBehavior: {
          strictTransportSecurity: {
            accessControlMaxAge: cdk.Duration.seconds(31_536_000),
            includeSubdomains: true,
            preload: true,
            override: true,
          },
          contentTypeOptions: { override: true },
          referrerPolicy: {
            referrerPolicy:
              cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
            override: true,
          },
          contentSecurityPolicy: {
            contentSecurityPolicy: csp,
            override: true,
          },
        },
        customHeadersBehavior: {
          customHeaders: [
            {
              header: "Permissions-Policy",
              value: "camera=(), microphone=(), geolocation=()",
              override: true,
            },
            {
              header: "Cross-Origin-Opener-Policy",
              value: "same-origin",
              override: true,
            },
          ],
        },
      },
    );

    this.distribution = new cloudfront.Distribution(
      this,
      "PublicWebsiteDistribution",
      {
        defaultRootObject: "index.html",
        domainNames: [domainName.valueAsString],
        certificate,
        defaultBehavior: {
          origin,
          viewerProtocolPolicy:
            cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
          cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
          responseHeadersPolicy: securityHeaders,
        },
        errorResponses: [
          {
            httpStatus: 403,
            responseHttpStatus: 200,
            responsePagePath: "/index.html",
            ttl: cdk.Duration.minutes(5),
          },
          {
            httpStatus: 404,
            responseHttpStatus: 200,
            responsePagePath: "/index.html",
            ttl: cdk.Duration.minutes(5),
          },
        ],
        // CloudFront access logging (CKV_AWS_86)
        enableLogging: true,
        logBucket: this.accessLogsBucket,
        logFilePrefix: "cloudfront/",
      }
    );

    // Add explicit bucket policy to grant CloudFront OAC access to the imported bucket.
    // This is required because CDK cannot auto-add policies to imported buckets.
    const bucketPolicy = new s3.BucketPolicy(this, "PublicWebsiteBucketPolicy", {
      bucket: this.bucket,
    });

    bucketPolicy.document.addStatements(
      new iam.PolicyStatement({
        sid: "AllowCloudFrontServicePrincipalReadOnly",
        effect: iam.Effect.ALLOW,
        actions: ["s3:GetObject"],
        resources: [this.bucket.arnForObjects("*")],
        principals: [new iam.ServicePrincipal("cloudfront.amazonaws.com")],
        conditions: {
          StringEquals: {
            "AWS:SourceArn": cdk.Arn.format({
              service: "cloudfront",
              resource: "distribution",
              resourceName: this.distribution.distributionId,
              region: "",
            }, this),
          },
        },
      })
    );

    new cdk.CfnOutput(this, "PublicWebsiteBucketName", {
      value: this.bucket.bucketName,
    });

    new cdk.CfnOutput(this, "PublicWebsiteDistributionId", {
      value: this.distribution.distributionId,
    });

    new cdk.CfnOutput(this, "PublicWebsiteDistributionDomain", {
      value: this.distribution.distributionDomainName,
    });

    new cdk.CfnOutput(this, "CloudFrontAccessLogsBucketName", {
      value: this.accessLogsBucket.bucketName,
    });
  }
}
