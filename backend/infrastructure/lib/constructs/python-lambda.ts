import * as fs from "node:fs";
import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import * as kms from "aws-cdk-lib/aws-kms";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as sqs from "aws-cdk-lib/aws-sqs";
import type { Construct } from "constructs";

export interface PythonLambdaFactoryProps {
  /** Directory containing handler.py and optional requirements.txt */
  readonly entryDir: string;
  /** Lambda handler string, e.g. handler.lambda_handler */
  readonly handler?: string;
  readonly runtime?: lambda.Runtime;
  readonly architecture?: lambda.Architecture;
  readonly memorySize?: number;
  readonly timeout?: cdk.Duration;
  readonly environment?: Record<string, string>;
  /**
   * KMS key used for environment variable encryption (Checkov CKV_AWS_173).
   * When omitted, AWS-managed encryption applies and Checkov flags it.
   */
  readonly environmentEncryptionKey?: kms.IKey;
  /**
   * KMS key used for the explicit CloudWatch log group encryption
   * (Checkov CKV_AWS_158). When omitted, the log group is unencrypted at
   * the application layer (CloudWatch still encrypts at rest with an
   * AWS-managed key, but Checkov flags it).
   *
   * The caller is responsible for granting the CloudWatch Logs service
   * principal `kms:Encrypt*`/`Decrypt*`/`GenerateDataKey*` on the key. See
   * `LxsoftwareStack` for the standard service-principal grant.
   */
  readonly logEncryptionKey?: kms.IKey;
  /**
   * SQS queue used for failed async invocations (Checkov CKV_AWS_116).
   * Sharing a single DLQ across multiple low-traffic Lambdas avoids
   * incurring an extra KMS-managed SQS queue per function.
   */
  readonly deadLetterQueue?: sqs.IQueue;
  /**
   * Reserved concurrency limit (Checkov CKV_AWS_115). When set, bounds
   * the blast radius of a runaway invocation rate. Intentionally **not**
   * defaulted: AWS enforces an `UnreservedConcurrentExecution` floor of
   * 100, so on accounts whose regional concurrency limit is at that
   * floor (small / new accounts), any positive reservation would push
   * unreserved below the floor and CloudFormation would reject the
   * update with `InvalidRequest`. Callers that have requested a higher
   * regional concurrency limit can opt in by passing a value here; the
   * suppression for `CKV_AWS_115` lives in `CheckovSuppressionAspect`
   * with the same rationale.
   */
  readonly reservedConcurrentExecutions?: number;
  /**
   * Override the log group's removal policy. Defaults to DESTROY so dev/
   * preview stack teardowns don't leave orphan log groups; production
   * callers can pass RETAIN for compliance retention.
   */
  readonly logRemovalPolicy?: cdk.RemovalPolicy;
}

function requirementsNeedPip(reqPath: string): boolean {
  if (!fs.existsSync(reqPath)) {
    return false;
  }
  const text = fs.readFileSync(reqPath, "utf8");
  const nonComment = text
    .split("\n")
    .map((line) => line.replace(/#.*/, "").trim())
    .filter(Boolean);
  return nonComment.length > 0;
}

function copyDirRecursive(src: string, dest: string): void {
  fs.mkdirSync(dest, { recursive: true });
  for (const name of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, name.name);
    const destPath = path.join(dest, name.name);
    if (name.name === "__pycache__" || name.name === ".pytest_cache") {
      continue;
    }
    if (name.isDirectory()) {
      copyDirRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function tryLocalPythonBundle(entry: string, outputDir: string): boolean {
  const req = path.join(entry, "requirements.txt");
  if (requirementsNeedPip(req) && process.env.CDK_SKIP_PYTHON_PIP !== "1") {
    return false;
  }
  copyDirRecursive(entry, outputDir);
  return true;
}

/**
 * Creates a Python 3.12 Lambda with Docker-based bundling (recursive copy of
 * sources + pip when requirements.txt has packages). Local bundling only runs
 * when there are no pip dependencies so macOS wheels are never copied into a
 * Linux ARM runtime bundle. `CDK_SKIP_PYTHON_PIP=1` copies sources without
 * pip for template-only synth (Checkov).
 *
 * Wires up the standard hardening expected by Checkov on every application
 * Lambda:
 * - Customer-managed KMS encryption for environment variables (CKV_AWS_173)
 * - Customer-managed KMS encryption on the CloudWatch log group (CKV_AWS_158)
 * - Async-invocation dead-letter queue (CKV_AWS_116)
 *
 * Reserved concurrency (CKV_AWS_115) and VPC configuration (CKV_AWS_117)
 * are intentionally omitted — see `CheckovSuppressionAspect` in
 * `lib/constructs/checkov-suppressions.ts` for the rationale (account-level
 * concurrency floor and cost-vs-benefit, respectively).
 */
export function createPythonLambda(
  scope: Construct,
  id: string,
  props: PythonLambdaFactoryProps
): lambda.Function {
  const entry = path.resolve(props.entryDir);
  const handler = props.handler ?? "handler.lambda_handler";

  const logGroup = new logs.LogGroup(scope, `${id}LogGroup`, {
    retention: logs.RetentionDays.ONE_MONTH,
    removalPolicy: props.logRemovalPolicy ?? cdk.RemovalPolicy.DESTROY,
    encryptionKey: props.logEncryptionKey,
  });

  return new lambda.Function(scope, id, {
    runtime: props.runtime ?? lambda.Runtime.PYTHON_3_12,
    architecture: props.architecture ?? lambda.Architecture.ARM_64,
    handler,
    code: lambda.Code.fromAsset(entry, {
      bundling: {
        image: lambda.Runtime.PYTHON_3_12.bundlingImage,
        platform: "linux/arm64",
        local: {
          tryBundle(outputDir: string) {
            return tryLocalPythonBundle(entry, outputDir);
          },
        },
        command: [
          "bash",
          "-c",
          [
            "set -euo pipefail",
            "export PIP_ROOT_USER_ACTION=ignore",
            "if [[ -f requirements.txt ]]; then pip install -r requirements.txt -t /asset-output; fi",
            "shopt -s dotglob nullglob",
            "for item in *; do",
            "  if [[ \"$item\" == requirements.txt ]]; then continue; fi",
            "  if [[ -d \"$item\" ]]; then cp -a \"$item\" /asset-output/; fi",
            "done",
            "for f in *.py; do",
            "  [[ -f \"$f\" ]] && cp -a \"$f\" /asset-output/",
            "done",
          ].join(" "),
        ],
      },
    }),
    memorySize: props.memorySize ?? 512,
    timeout: props.timeout ?? cdk.Duration.seconds(10),
    environment: props.environment,
    environmentEncryption: props.environmentEncryptionKey,
    logGroup,
    deadLetterQueue: props.deadLetterQueue,
    deadLetterQueueEnabled: props.deadLetterQueue ? true : undefined,
    // Pass-through only when explicitly set; see prop docstring above for
    // the AWS-account-level rationale for not defaulting this.
    ...(props.reservedConcurrentExecutions !== undefined
      ? { reservedConcurrentExecutions: props.reservedConcurrentExecutions }
      : {}),
  });
}
