import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import type { Construct } from "constructs";
import { ADMIN_WEB_HOSTNAME } from "./shared-contracts";

export interface LxsoftwareAdminWebStackProps extends cdk.StackProps {
  /** Admin HTTP API origin (https://{api-id}.execute-api.{region}.amazonaws.com) for CSP connect-src */
  readonly cspApiConnectOrigin: string;
  /**
   * Space-delimited origins for the private assets bucket the admin SPA
   * uploads PDFs / images to via presigned POST. Must include **both**:
   *
   *   * `https://<bucket>.s3.amazonaws.com`          (legacy global virtual-hosted)
   *   * `https://<bucket>.s3.<region>.amazonaws.com` (regional virtual-hosted)
   *
   * boto3 in the admin Lambda (default config) currently signs the legacy
   * global form; a future SDK / endpoint upgrade may switch to the regional
   * form without notice. Allow-listing both prevents the browser CSP from
   * blocking the upload `fetch()` either way.
   */
  readonly cspAssetsConnectOrigins: string;
}

/**
 * Admin SPA delivery: private S3 origin + CloudFront distribution + WAF/CSP.
 *
 * All physical names use the `lxsoftware-admin-*` prefix.
 */
export class LxsoftwareAdminWebStack extends cdk.Stack {
  public readonly bucket: s3.Bucket;
  public readonly distribution: cloudfront.Distribution;
  public readonly accessLogsBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: LxsoftwareAdminWebStackProps) {
    super(scope, id, props);

    const resourcePrefix = "lxsoftware-admin";

    const domainName = new cdk.CfnParameter(this, "AdminWebDomainName", {
      type: "String",
      description: "Custom domain for the admin SPA (CloudFront alias).",
      default: ADMIN_WEB_HOSTNAME,
    });

    const certificateArn = new cdk.CfnParameter(this, "AdminWebCertificateArn", {
      type: "String",
      description: "ACM certificate ARN in us-east-1 for the admin domain (CloudFront).",
    });

    const cspCognitoConnectOrigin = new cdk.CfnParameter(
      this,
      "CspCognitoConnectOrigin",
      {
        type: "String",
        description:
          "Cognito OAuth origin for CSP connect-src (no path), e.g. https://auth.example.com",
      }
    );

    const wafWebAclArn = new cdk.CfnParameter(this, "WafWebAclArn", {
      type: "String",
      description: "Optional WAFv2 Web ACL ARN to attach to CloudFront (leave empty to disable).",
      default: "",
      allowedPattern: "^$|^arn:aws:wafv2:us-east-1:[0-9]{12}:global/webacl/.+$",
      constraintDescription:
        "Must be empty or a WAFv2 global Web ACL ARN in us-east-1 for CloudFront.",
    });

    const hasWaf = new cdk.CfnCondition(this, "HasWaf", {
      expression: cdk.Fn.conditionNot(
        cdk.Fn.conditionEquals(wafWebAclArn.valueAsString, "")
      ),
    });

    const bucketName = [resourcePrefix, "web", cdk.Aws.ACCOUNT_ID, cdk.Aws.REGION].join(
      "-"
    );

    const logsBucketName = [
      resourcePrefix,
      "web-logs",
      cdk.Aws.ACCOUNT_ID,
      cdk.Aws.REGION,
    ].join("-");

    this.accessLogsBucket = new s3.Bucket(this, "CloudFrontAccessLogsBucket", {
      bucketName: logsBucketName,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
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

    this.bucket = new s3.Bucket(this, "AdminWebBucket", {
      bucketName,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      serverAccessLogsBucket: this.accessLogsBucket,
      serverAccessLogsPrefix: "s3-web-origin/",
    });

    const certificate = acm.Certificate.fromCertificateArn(
      this,
      "AdminWebCertificate",
      certificateArn.valueAsString
    );

    const spaRewrite = new cloudfront.Function(this, "SpaRewrite", {
      code: cloudfront.FunctionCode.fromInline(`function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.startsWith('/assets/')) return request;
  if (uri.indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}`),
    });

    const cspValue = cdk.Fn.join("", [
      "default-src 'self'; script-src 'self'; connect-src 'self' ",
      cspCognitoConnectOrigin.valueAsString,
      " ",
      props.cspApiConnectOrigin,
      " ",
      props.cspAssetsConnectOrigins,
      "; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
    ]);

    const securityHeadersPolicy = new cloudfront.ResponseHeadersPolicy(
      this,
      "AdminSecurityHeaders",
      {
        responseHeadersPolicyName: `${resourcePrefix}-security-headers`,
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
            contentSecurityPolicy: cspValue,
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
          ],
        },
      }
    );

    const origin = origins.S3BucketOrigin.withOriginAccessControl(this.bucket);

    this.distribution = new cloudfront.Distribution(
      this,
      "AdminWebDistribution",
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
          responseHeadersPolicy: securityHeadersPolicy,
          functionAssociations: [
            {
              function: spaRewrite,
              eventType: cloudfront.FunctionEventType.VIEWER_REQUEST,
            },
          ],
        },
        errorResponses: [
          {
            httpStatus: 404,
            responseHttpStatus: 200,
            responsePagePath: "/index.html",
            ttl: cdk.Duration.minutes(5),
          },
        ],
        enableLogging: true,
        logBucket: this.accessLogsBucket,
        logFilePrefix: "cloudfront/",
      }
    );

    const cfnDist = this.distribution.node.defaultChild as cloudfront.CfnDistribution;
    cfnDist.addPropertyOverride(
      "DistributionConfig.WebACLId",
      cdk.Fn.conditionIf(
        hasWaf.logicalId,
        wafWebAclArn.valueAsString,
        cdk.Aws.NO_VALUE
      )
    );

    // The bucket's own policy (`AdminWebBucket/Policy`, created by
    // `enforceSSL`) already carries the OAC read grant that
    // `S3BucketOrigin.withOriginAccessControl` adds for an owned bucket:
    // statement 0 is the `aws:SecureTransport` deny, statement 1 is the
    // CloudFront `s3:GetObject` allow. Naming that statement forces one
    // PutBucketPolicy of the complete document on the next deploy.
    const bucketOwnPolicy = this.bucket.policy;
    if (!bucketOwnPolicy) {
      throw new Error("AdminWebBucket has no bucket policy; enforceSSL must stay on");
    }
    const cfnBucketOwnPolicy = bucketOwnPolicy.node
      .defaultChild as s3.CfnBucketPolicy;
    cfnBucketOwnPolicy.addPropertyOverride(
      "PolicyDocument.Statement.1.Sid",
      "AllowCloudFrontServicePrincipalReadOnly"
    );

    // Legacy duplicate of that OAC grant. A bucket holds one policy, so two
    // AWS::S3::BucketPolicy resources on the same bucket race: whichever
    // CloudFormation applied last was the live policy, and the other one's
    // statements (here the HTTPS-only deny) were silently dropped.
    //
    // Deleting an AWS::S3::BucketPolicy calls DeleteBucketPolicy, which would
    // wipe the merged policy applied above in the same deploy. Retain it for
    // one deploy so a later removal is a template-only change; see
    // docs/deployment/admin-website.md ("Admin web bucket policy").
    const legacyBucketPolicy = new s3.BucketPolicy(
      this,
      "AdminWebBucketPolicy",
      {
        bucket: this.bucket,
        removalPolicy: cdk.RemovalPolicy.RETAIN,
      }
    );
    legacyBucketPolicy.document.addStatements(
      new iam.PolicyStatement({
        sid: "AllowCloudFrontServicePrincipalReadOnly",
        effect: iam.Effect.ALLOW,
        actions: ["s3:GetObject"],
        resources: [this.bucket.arnForObjects("*")],
        principals: [new iam.ServicePrincipal("cloudfront.amazonaws.com")],
        conditions: {
          StringEquals: {
            "AWS:SourceArn": cdk.Arn.format(
              {
                service: "cloudfront",
                resource: "distribution",
                resourceName: this.distribution.distributionId,
                region: "",
              },
              this
            ),
          },
        },
      })
    );
    // Deploy order: the complete policy must be the last PutBucketPolicy.
    bucketOwnPolicy.node.addDependency(legacyBucketPolicy);

    new cdk.CfnOutput(this, "AdminWebBucketName", {
      value: this.bucket.bucketName,
      exportName: "lxsoftware-admin-web-AdminWebBucketName",
    });

    new cdk.CfnOutput(this, "AdminWebDistributionId", {
      value: this.distribution.distributionId,
      exportName: "lxsoftware-admin-web-AdminWebDistributionId",
    });

    new cdk.CfnOutput(this, "AdminWebDistributionDomain", {
      value: this.distribution.distributionDomainName,
      exportName: "lxsoftware-admin-web-AdminWebDistributionDomain",
    });

    new cdk.CfnOutput(this, "AdminWebLoggingBucketName", {
      value: this.accessLogsBucket.bucketName,
      exportName: "lxsoftware-admin-web-AdminWebLoggingBucketName",
    });
  }
}
