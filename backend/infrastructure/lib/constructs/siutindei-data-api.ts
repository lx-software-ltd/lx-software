import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as scheduler from "aws-cdk-lib/aws-scheduler";
import * as schedulerTargets from "aws-cdk-lib/aws-scheduler-targets";
import * as cr from "aws-cdk-lib/custom-resources";
import { Construct, type IConstruct } from "constructs";
import { createPythonLambda } from "./python-lambda";

export const SIUTINDEI_DB_SECRET_NAME_DEFAULT =
  "lxsoftware-siutindei-database-credentials";

export interface AuroraDataApiSetupProps {
  readonly clusterArn: string;
  /** Complete secret ARN when known; otherwise leave blank and pass secretName. */
  readonly secretArn: string;
  readonly secretName: string;
  readonly databaseName?: string;
  /**
   * Apply ``receivables.sql`` after enabling the HTTP endpoint.
   * Leave false for a database this stack only reads (Evolve Sprouts).
   */
  readonly applySql?: boolean;
  readonly scheduleName?: string;
  readonly scheduleDescription?: string;
  readonly scheduleInput?: Record<string, string>;
  readonly httpEndpointPhysicalId?: string;
  readonly condition: cdk.CfnCondition;
  readonly environmentEncryptionKey: cdk.aws_kms.IKey;
  readonly logEncryptionKey: cdk.aws_kms.IKey;
  readonly deadLetterQueue: cdk.aws_sqs.IQueue;
}

/** @deprecated Use {@link AuroraDataApiSetupProps}. Construct ids are unchanged. */
export type SiutindeiDataApiSetupProps = AuroraDataApiSetupProps;

/**
 * Turns on the RDS HTTP Data API for an existing Aurora cluster.
 *
 * Siu Tin Dei also applies ``receivables.sql``. Evolve Sprouts only enables
 * the HTTP endpoint (``applySql: false``); this stack never writes that
 * database.
 *
 * A 15-minute EventBridge Scheduler re-enables the HTTP endpoint (and
 * reapplies the script when ``applySql`` is true) so a later product-stack
 * deploy cannot leave Data API off. The product CDK should still set
 * ``enableDataApi: true``; the schedule is the guard.
 *
 * Delete is a no-op: we do not disable the HTTP endpoint or drop tables.
 *
 * The EventBridge role is created inside this construct and shares
 * ``condition``. CDK's default target role is a stack-level resource and
 * would fail CloudFormation when the cluster ARN (and this construct) is
 * absent.
 */
export class AuroraDataApiSetup extends Construct {
  /** Secrets Manager ARN Data API / AdminApiFn should use. */
  public readonly resolvedSecretArn: string;

  constructor(scope: Construct, id: string, props: AuroraDataApiSetupProps) {
    super(scope, id);

    const stack = cdk.Stack.of(this);
    const databaseName = props.databaseName ?? "siutindei";
    const applySql = props.applySql ?? true;
    const httpEndpointPhysicalId =
      props.httpEndpointPhysicalId ?? "siutindei-aurora-http-endpoint";
    const schemaDir = path.join(__dirname, "../../../lambda/siutindei_schema");
    const sqlPath = path.join(schemaDir, "receivables.sql");
    // Hash the script and the splitter so a packaging/split fix retriggers
    // the custom resource (sql-only hash missed the ASWITH bugfix).
    const sqlHash = crypto
      .createHash("sha256")
      .update(fs.readFileSync(sqlPath))
      .update(fs.readFileSync(path.join(schemaDir, "sql_split.py")))
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
    const secretNameArns = props.secretName
      ? [
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
        ]
      : [props.secretArn];

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
        physicalResourceId: cr.PhysicalResourceId.of(httpEndpointPhysicalId),
      },
      onUpdate: {
        service: "RDS",
        action: "enableHttpEndpoint",
        parameters: { ResourceArn: props.clusterArn },
        physicalResourceId: cr.PhysicalResourceId.of(httpEndpointPhysicalId),
      },
    });

    const endpointFn = createPythonLambda(
      this,
      applySql ? "ReceivablesSchemaFn" : "HttpEndpointFn",
      {
        entryDir: path.join(__dirname, "../../../lambda/siutindei_schema"),
        handler: "handler.lambda_handler",
        timeout: cdk.Duration.minutes(3),
        memorySize: 256,
        environmentEncryptionKey: props.environmentEncryptionKey,
        logEncryptionKey: props.logEncryptionKey,
        deadLetterQueue: props.deadLetterQueue,
        environment: applySql
          ? {
              SIUTINDEI_CLUSTER_ARN: props.clusterArn,
              SIUTINDEI_DB_SECRET_ARN: this.resolvedSecretArn,
              SIUTINDEI_DB_NAME: databaseName,
            }
          : {
              DATA_API_CLUSTER_ARN: props.clusterArn,
              DATA_API_APPLY_SQL: "false",
            },
      }
    );
    endpointFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["rds:EnableHttpEndpoint"],
        resources: [props.clusterArn],
      })
    );
    endpointFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["rds:DescribeDBClusters"],
        resources: ["*"],
      })
    );
    if (applySql) {
      endpointFn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ["rds-data:ExecuteStatement"],
          resources: [props.clusterArn],
        })
      );
      endpointFn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
          resources: [this.resolvedSecretArn, ...secretNameArns],
        })
      );
      // DescribeSecret.KmsKeyId is a key ARN for a customer key and an alias
      // for aws/secretsmanager. kms:Decrypt does not accept an alias, so the
      // grant stays on * through Secrets Manager. A tightened CMK policy must
      // still allow this role.
      endpointFn.addToRolePolicy(
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
      endpointFn.addPermission("CloudFormationInvoke", {
        principal: new iam.ServicePrincipal("cloudformation.amazonaws.com"),
        action: "lambda:InvokeFunction",
        // CKV_AWS_364: a service principal without SourceAccount/SourceArn
        // lets any account's CloudFormation invoke this function.
        sourceAccount: cdk.Aws.ACCOUNT_ID,
      });

      const schema = new cdk.CustomResource(this, "ReceivablesSchema", {
        serviceToken: endpointFn.functionArn,
        // Without this CloudFormation waits an hour for a provider that never
        // responds (e.g. the Lambda failed at init), which outlives the CI
        // OIDC token. The Lambda times out at 3 min and async retries twice.
        serviceTimeout: cdk.Duration.minutes(15),
        properties: {
          clusterArn: props.clusterArn,
          secretArn: this.resolvedSecretArn,
          database: databaseName,
          // Re-run when the script or splitter changes.
          sqlHash,
        },
      });
      schema.node.addDependency(enableHttp);
      schema.node.addDependency(describeSecret);
    }

    const scheduleInput = props.scheduleInput ?? {
      internal: "siutindei_data_api_ensure",
      boardKey: "siuTinDei",
    };
    // Role lives under this construct so ``condition`` applies. CDK's
    // default Scheduler role is created at the stack and would reference
    // a function that does not exist when the cluster ARN is blank.
    const scheduleRole = new iam.Role(this, "EnsureScheduleRole", {
      assumedBy: new iam.ServicePrincipal("scheduler.amazonaws.com"),
    });
    scheduleRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ["lambda:InvokeFunction"],
        resources: [endpointFn.functionArn, `${endpointFn.functionArn}:*`],
      })
    );
    new scheduler.Schedule(this, "EnsureHttpEndpoint", {
      scheduleName:
        props.scheduleName ?? "lxsoftware-admin-siutindei-data-api-ensure",
      description:
        props.scheduleDescription ??
        "Re-enable the siutindei Aurora HTTP Data API and reapply receivables.sql so a product-stack deploy cannot drift it off.",
      schedule: scheduler.ScheduleExpression.rate(cdk.Duration.minutes(15)),
      target: new schedulerTargets.LambdaInvoke(endpointFn, {
        input: scheduler.ScheduleTargetInput.fromObject(scheduleInput),
        retryAttempts: 2,
        role: scheduleRole,
      }),
    });

    cdk.Aspects.of(this).add({
      visit(node: IConstruct) {
        if (
          node instanceof cdk.CfnResource &&
          !(node instanceof cdk.CfnCondition) &&
          !node.cfnOptions.condition
        ) {
          node.cfnOptions.condition = props.condition;
        }
      },
    });
  }
}

/** Construct ids stay ``SiutindeiDataApi`` / ``EvolvesproutsDataApi``. */
export { AuroraDataApiSetup as SiutindeiDataApiSetup };
