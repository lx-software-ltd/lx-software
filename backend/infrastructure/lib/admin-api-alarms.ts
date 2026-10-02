import * as cdk from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as logs from "aws-cdk-lib/aws-logs";
import type * as lambda from "aws-cdk-lib/aws-lambda";

/** Metric filters and alarms for the public API authorizer and AdminApiFn. */
export function defineAdminApiAlarms(
  scope: cdk.Stack,
  input: {
    readonly adminFn: lambda.Function;
    readonly publicApiKeyAuthorizerFn: lambda.Function;
  },
) {
  const { adminFn, publicApiKeyAuthorizerFn } = input;
  // Term patterns, not JSON patterns: the Python runtime prefixes each
  // line with "[LEVEL]\ttimestamp\trequest-id\t", so the event is not a
  // JSON document and `{ $.tag = ... }` would never match.
  new logs.MetricFilter(scope, "PublicApiKeyDeniedFilter", {
    logGroup: publicApiKeyAuthorizerFn.logGroup,
    filterPattern: logs.FilterPattern.allTerms("public_api_key_denied"),
    metricNamespace: "lxsoftware/public-api",
    metricName: "ApiKeyDenied",
    metricValue: "1",
  });
  new cloudwatch.Alarm(scope, "PublicApiKeyDeniedAlarm", {
    metric: new cloudwatch.Metric({
      namespace: "lxsoftware/public-api",
      metricName: "ApiKeyDenied",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    }),
    threshold: 20,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    alarmDescription: "Burst of denied public API key attempts.",
  });
  new logs.MetricFilter(scope, "PublicApiBoardFullFilter", {
    logGroup: adminFn.logGroup,
    filterPattern: logs.FilterPattern.allTerms(
      "public_api_access",
      "siutindei-board-full"
    ),
    metricNamespace: "lxsoftware/public-api",
    metricName: "BoardFullAccess",
    metricValue: "1",
  });
  new logs.MetricFilter(scope, "PublicApiWriteFilter", {
    logGroup: adminFn.logGroup,
    filterPattern: logs.FilterPattern.allTerms("public_api_write"),
    metricNamespace: "lxsoftware/public-api",
    metricName: "PublicApiWrite",
    metricValue: "1",
  });
  new cloudwatch.Alarm(scope, "PublicApiWriteAlarm", {
    metric: new cloudwatch.Metric({
      namespace: "lxsoftware/public-api",
      metricName: "PublicApiWrite",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    }),
    threshold: 20,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    alarmDescription: "Burst of public API-key board writes.",
  });
  new cloudwatch.Alarm(scope, "PublicApiBoardFullAlarm", {
    metric: new cloudwatch.Metric({
      namespace: "lxsoftware/public-api",
      metricName: "BoardFullAccess",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    }),
    threshold: 30,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    alarmDescription: "Jump in siutindei-board-full public API reads.",
  });
  // Replaces RecursiveInvocationsDropped after RecursiveLoop Allow.
  // Observed 5-min peak on 2026-09-14/15 was 145 (evening standup). The
  // name includes "siutindei" so hourly board_cache_refresh / aws_list_alarms
  // surfaces a new ALARM as an architect/CTO task.
  new cloudwatch.Alarm(scope, "AdminApiInvocationsAlarm", {
    alarmName: "lxsoftware-admin-siutindei-admin-api-invocations",
    metric: adminFn.metricInvocations({
      period: cdk.Duration.minutes(5),
      statistic: "Sum",
    }),
    threshold: 250,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    alarmDescription:
      "AdminApiFn invoke burst (tight self-invoke runaway). 5-min peak before Allow was 145.",
  });
}
