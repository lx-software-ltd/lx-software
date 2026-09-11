import * as cdk from "aws-cdk-lib";
import type { IConstruct } from "constructs";

/**
 * CDK Aspect that injects in-source Checkov skip metadata onto resources
 * that Checkov flags but which are CDK-internal (deployment-time only) and
 * therefore cannot meaningfully comply with the corresponding controls.
 *
 * Pairs with the `Filter in-source suppressed Checkov findings` step in
 * `.github/workflows/security.yml`, which strips SARIF entries whose only
 * suppression is `kind == "inSource"` so they don't surface in GitHub
 * Code Scanning.
 *
 * Mirrors the lcacchiani/evolvesprouts approach so node-path matching stays
 * consistent across both repositories.
 */
export class CheckovSuppressionAspect implements cdk.IAspect {
  public visit(node: IConstruct): void {
    if (!(node instanceof cdk.CfnResource)) {
      return;
    }

    const cfnType = node.cfnResourceType;
    const nodePath = node.node.path;

    if (cfnType === "AWS::Lambda::Function") {
      // CDK-internal Lambdas: AwsCustomResource handler + S3 bucket
      // notification handler. They run only during deployments, are AWS-
      // managed runtimes, and have no business value to throttle, attach
      // a DLQ to, or push into a VPC.
      const isAwsCustomResource = nodePath.includes(
        "AWS679f53fac002430cb0da5b7982bd2287"
      );
      const isBucketNotifications = nodePath.includes(
        "BucketNotificationsHandler050a0587b7544547bf325f094a3db834"
      );

      if (isAwsCustomResource || isBucketNotifications) {
        const which = isAwsCustomResource
          ? "CDK-internal AwsCustomResource Lambda"
          : "CDK-internal BucketNotifications Lambda";
        node.addMetadata("checkov", {
          skip: [
            {
              id: "CKV_AWS_115",
              comment: `${which} - runs only during deployments, no concurrency control needed.`,
            },
            {
              id: "CKV_AWS_116",
              comment: `${which} - runs only during deployments, no DLQ needed.`,
            },
            {
              id: "CKV_AWS_117",
              comment: `${which} - calls AWS service APIs over the public Lambda interface; VPC adds NAT cost without security benefit.`,
            },
          ],
        });
      }

      // Application Lambdas: VPC suppression with cost rationale. They
      // legitimately call public HTTPS APIs (Frankfurter, OpenRouter,
      // Cognito) plus AWS APIs over the Lambda public interface; placing
      // them behind a NAT Gateway (~$32/mo) or four VPC interface
      // endpoints (S3, DDB, SES, Secrets Manager — ~$28/mo) provides no
      // additional security benefit since traffic to AWS is already
      // TLS-internal.
      const isAppLambda =
        nodePath.endsWith("/AdminApiFn/Resource") ||
        nodePath.endsWith("/InboundStatementMailFn/Resource") ||
        nodePath.endsWith("/PreTokenGenerationFn/Resource") ||
        nodePath.endsWith("/PublicApiKeyAuthorizerFn/Resource") ||
        nodePath.endsWith("/ReceivablesSchemaFn/Resource");

      if (isAppLambda) {
        node.addMetadata("checkov", {
          skip: [
            {
              id: "CKV_AWS_115",
              comment:
                "AWS account regional concurrency limit is at the 100-unit floor (UnreservedConcurrentExecution minimum). Any positive ReservedConcurrentExecutions on these Lambdas would push the unreserved pool below the floor and CloudFormation rejects the update. Account-level concurrency monitoring + per-Lambda alarms cover this control until the regional limit is raised, at which point reservations can be re-enabled per-function.",
            },
            {
              id: "CKV_AWS_117",
              comment:
                "Admin Lambdas call public HTTPS APIs (Frankfurter, OpenRouter) and AWS APIs over the public Lambda interface. VPC + NAT/VPC-endpoints adds material cost ($30+/mo) with no security benefit since AWS traffic is already TLS-internal and presigned URLs are scoped per-request.",
            },
          ],
        });
      }
    }
  }
}
