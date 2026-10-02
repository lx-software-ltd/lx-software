import * as cdk from "aws-cdk-lib";
import type * as kms from "aws-cdk-lib/aws-kms";
import type * as sqs from "aws-cdk-lib/aws-sqs";
import { AuroraDataApiSetup } from "./constructs/siutindei-data-api";

/** Aurora HTTP Data API setups. Construct ids stay SiutindeiDataApi and EvolvesproutsDataApi. */
export function defineProductDataApis(
  scope: cdk.Stack,
  input: {
    readonly siutindeiClusterArn: cdk.CfnParameter;
    readonly siutindeiDbSecretArn: cdk.CfnParameter;
    readonly siutindeiDbSecretName: cdk.CfnParameter;
    readonly evolvesproutsClusterArn: cdk.CfnParameter;
    readonly evolvesproutsDbSecretArn: cdk.CfnParameter;
    readonly evolvesproutsDbSecretName: cdk.CfnParameter;
    readonly sharedEncryptionKey: kms.IKey;
    readonly lambdaDeadLetterQueue: sqs.Queue;
  },
) {
  const {
    siutindeiClusterArn,
    siutindeiDbSecretArn,
    siutindeiDbSecretName,
    evolvesproutsClusterArn,
    evolvesproutsDbSecretArn,
    evolvesproutsDbSecretName,
    sharedEncryptionKey,
    lambdaDeadLetterQueue,
  } = input;
  // Cluster ARN only: CDK enables the HTTP Data API and applies
  // receivables.sql. Secret ARN is optional — blank resolves the
  // default siutindei master-secret name.
  const hasSiutindeiDataApi = new cdk.CfnCondition(scope, "HasSiutindeiDataApi", {
    expression: cdk.Fn.conditionNot(
      cdk.Fn.conditionEquals(siutindeiClusterArn.valueAsString, "")
    ),
  });
  const siutindeiDataApi = new AuroraDataApiSetup(scope, "SiutindeiDataApi", {
    clusterArn: siutindeiClusterArn.valueAsString,
    secretArn: siutindeiDbSecretArn.valueAsString,
    secretName: siutindeiDbSecretName.valueAsString,
    condition: hasSiutindeiDataApi,
    environmentEncryptionKey: sharedEncryptionKey,
    logEncryptionKey: sharedEncryptionKey,
    deadLetterQueue: lambdaDeadLetterQueue,
  });
  const hasEvolvesproutsDataApi = new cdk.CfnCondition(scope, "HasEvolvesproutsDataApi", {
    expression: cdk.Fn.conditionAnd(
      cdk.Fn.conditionNot(cdk.Fn.conditionEquals(evolvesproutsClusterArn.valueAsString, "")),
      cdk.Fn.conditionOr(
        cdk.Fn.conditionNot(cdk.Fn.conditionEquals(evolvesproutsDbSecretArn.valueAsString, "")),
        cdk.Fn.conditionNot(cdk.Fn.conditionEquals(evolvesproutsDbSecretName.valueAsString, ""))
      )
    ),
  });
  const evolvesproutsDataApi = new AuroraDataApiSetup(scope, "EvolvesproutsDataApi", {
    clusterArn: evolvesproutsClusterArn.valueAsString,
    secretArn: evolvesproutsDbSecretArn.valueAsString,
    secretName: evolvesproutsDbSecretName.valueAsString,
    databaseName: "evolvesprouts",
    applySql: false,
    scheduleName: "lxsoftware-admin-evolvesprouts-data-api-ensure",
    scheduleDescription:
      "Re-enable the Evolve Sprouts Aurora HTTP Data API. This stack does not apply SQL there.",
    scheduleInput: { internal: "data_api_ensure", applySql: "false" },
    httpEndpointPhysicalId: "evolvesprouts-aurora-http-endpoint",
    condition: hasEvolvesproutsDataApi,
    environmentEncryptionKey: sharedEncryptionKey,
    logEncryptionKey: sharedEncryptionKey,
    deadLetterQueue: lambdaDeadLetterQueue,
  });
  return {
    hasSiutindeiDataApi,
    siutindeiDataApi,
    hasEvolvesproutsDataApi,
    evolvesproutsDataApi,
  };
}
