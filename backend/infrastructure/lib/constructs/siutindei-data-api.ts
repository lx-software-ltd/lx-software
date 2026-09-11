import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as scheduler from "aws-cdk-lib/aws-scheduler";
import * as schedulerTargets from "aws-cdk-lib/aws-scheduler-targets";
import * as cr from "aws-cdk-lib/custom-resources";
import { Construct } from "constructs";
import { createPythonLambda } from "./python-lambda";

export const SIUTINDEI_DB_SECRET_NAME_DEFAULT =
  "lxsoftware-siutindei-database-credentials";

export interface SiutindeiDataApiSetupProps {
  readonly clusterArn: string;
  /** Complete secret ARN when known; otherwise leave blank and pass secretName. */
  readonly secretArn: string;
  readonly secretName: string;
  readonly databaseName?: string;
  readonly condition: cdk.CfnCondition;
  readonly environmentEncryptionKey: cdk.aws_kms.IKey;
  readonly logEncryptionKey: cdk.aws_kms.IKey;
  readonly deadLetterQueue: cdk.aws_sqs.IQueue;
}

/**
 * Turns on the RDS HTTP Data API for an existing Aurora cluster (owned by
 * the ``lxsoftware-siutindei`` stack) and applies ``receivables.sql``.
 *
 * A 15-minute EventBridge Scheduler re-enables the HTTP endpoint and
 * reapplies the script so a later siutindei deploy (which still creates the
 * cluster without ``enableDataApi: true``) cannot leave Data API off.
 * The product CDK should still set that flag; the schedule is the guard.
 *
 * Delete is a no-op: we do not disable the HTTP endpoint or drop tables.
 */
export class SiutindeiDataApiSetup extends Construct {
  /** Secrets Manager ARN Data API / AdminApiFn should use. */
  public readonly resolvedSecretArn: string;

  constructor(scope: Construct, id: string, props: SiutindeiDataApiSetupProps) {
    super(scope, id);

    const stack = cdk.Stack.of(this);
    const databaseName = props.databaseName ?? "siutindei";
    const sqlPath = path.join(
      __dirname,
      "../../../lambda/siutindei_schema/receivables.sql"
    );
    const sqlHash = crypto
      .createHash("sha256")
      .update(fs.readFileSync(sqlPath))
      .digest("hex")
      .slice(0, 16);
    const hasExplicitSecret = new cdk.CfnCondition(this, "HasExplicitSecret", {
      expression: cdk.Fn.conditionNot(cdk.Fn.conditionEquals(props.secretArn, "")),
    });
    const secretLookupId = cdk.Fn.conditionIf(
      hasExplicitSecret.logicalId,
      props.secretArn,
      props.secretName
    );
    const secretNameArns = [
      stack.formatArn({
        service: "secretsmanager",
        resource: "secret",
        resourceName: `${props.secretName}-??????`,
        arnFormat: cdk.ArnFormat.COLON_RESOURCE_NAME,
      }),
      stack.formatArn({
        service: "secretsmanager",
        resource: "secret",
        resourceName: `${props.secretName}*`,
        arnFormat: cdk.ArnFormat.COLON_RESOURCE_NAME,
      }),
      cdk.Fn.conditionIf(
        hasExplicitSecret.logicalId,
        props.secretArn,
        cdk.Aws.NO_VALUE
      ).toString(),
    ];

    const describeSecret = new cr.AwsCustomResource(this, "DescribeDbSecret", {
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ["secretsmanager:DescribeSecret"],
          resources: secretNameArns,
        }),
      ]),
      installLatestAwsSdk: false,
      onCreate: {
        service: "SecretsManager",
        action: "describeSecret",
        parameters: { SecretId: secretLookupId },
        physicalResourceId: cr.PhysicalResourceId.fromResponse("ARN"),
      },
      onUpdate: {
        service: "SecretsManager",
        action: "describeSecret",
        parameters: { SecretId: secretLookupId },
        physicalResourceId: cr.PhysicalResourceId.fromResponse("ARN"),
      },
    });

    this.resolvedSecretArn = describeSecret.getResponseField("ARN");

    const enableHttp = new cr.AwsCustomResource(this, "EnableHttpEndpoint", {
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ["rds:EnableHttpEndpoint"],
          resources: [props.clusterArn],
        }),
        new iam.PolicyStatement({
          actions: ["rds:DescribeDBClusters"],
          resources: ["*"],
        }),
      ]),
      installLatestAwsSdk: false,
      onCreate: {
        service: "RDS",
        action: "enableHttpEndpoint",
        parameters: { ResourceArn: props.clusterArn },
        physicalResourceId: cr.PhysicalResourceId.of(
          "siutindei-aurora-http-endpoint"
        ),
      },
      onUpdate: {
        service: "RDS",
        action: "enableHttpEndpoint",
        parameters: { ResourceArn: props.clusterArn },
        physicalResourceId: cr.PhysicalResourceId.of(
          "siutindei-aurora-http-endpoint"
        ),
      },
    });

    const schemaFn = createPythonLambda(this, "ReceivablesSchemaFn", {
      entryDir: path.join(__dirname, "../../../lambda/siutindei_schema"),
      handler: "handler.lambda_handler",
      timeout: cdk.Duration.minutes(3),
      memorySize: 256,
      environmentEncryptionKey: props.environmentEncryptionKey,
      logEncryptionKey: props.logEncryptionKey,
      deadLetterQueue: props.deadLetterQueue,
      environment: {
        SIUTINDEI_CLUSTER_ARN: props.clusterArn,
        SIUTINDEI_DB_SECRET_ARN: this.resolvedSecretArn,
        SIUTINDEI_DB_NAME: databaseName,
      },
    });
    schemaFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["rds-data:ExecuteStatement"],
        resources: [props.clusterArn],
      })
    );
    schemaFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["rds:EnableHttpEndpoint"],
        resources: [props.clusterArn],
      })
    );
    schemaFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["rds:DescribeDBClusters"],
        resources: ["*"],
      })
    );
    schemaFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
        resources: [this.resolvedSecretArn, ...secretNameArns],
      })
    );
    schemaFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["kms:Decrypt", "kms:DescribeKey"],
        resources: ["*"],
        conditions: {
          StringEquals: {
            "kms:ViaService": `secretsmanager.${stack.region}.amazonaws.com`,
          },
        },
      })
    );
    schemaFn.addPermission("CloudFormationInvoke", {
      principal: new iam.ServicePrincipal("cloudformation.amazonaws.com"),
      action: "lambda:InvokeFunction",
    });

    const schema = new cdk.CustomResource(this, "ReceivablesSchema", {
      serviceToken: schemaFn.functionArn,
      // Without this CloudFormation waits an hour for a provider that never
      // responds (e.g. the Lambda failed at init), which outlives the CI
      // OIDC token. The Lambda times out at 3 min and async retries twice.
      serviceTimeout: cdk.Duration.minutes(15),
      properties: {
        clusterArn: props.clusterArn,
        secretArn: this.resolvedSecretArn,
        database: databaseName,
        // Re-run when the script changes.
        sqlHash,
      },
    });
    schema.node.addDependency(enableHttp);
    schema.node.addDependency(describeSecret);

    // IAM-role target (no scheduler.amazonaws.com resource policy on the
    // function). Conditioned with the rest of this construct.
    new scheduler.Schedule(this, "EnsureHttpEndpoint", {
      scheduleName: "lxsoftware-admin-siutindei-data-api-ensure",
      description:
        "Re-enable the siutindei Aurora HTTP Data API and reapply receivables.sql so a product-stack deploy cannot drift it off.",
      schedule: scheduler.ScheduleExpression.rate(cdk.Duration.minutes(15)),
      target: new schedulerTargets.LambdaInvoke(schemaFn, {
        input: scheduler.ScheduleTargetInput.fromObject({
          internal: "siutindei_data_api_ensure",
          boardKey: "siuTinDei",
        }),
        retryAttempts: 2,
      }),
    });

    for (const child of this.node.findAll()) {
      if (
        child instanceof cdk.CfnResource &&
        !(child instanceof cdk.CfnCondition) &&
        !child.cfnOptions.condition
      ) {
        child.cfnOptions.condition = props.condition;
      }
    }
  }
}
