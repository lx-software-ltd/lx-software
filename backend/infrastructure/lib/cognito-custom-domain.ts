import * as cdk from "aws-cdk-lib";

/**
 * CloudFormation Validate resolves parameter defaults before Conditions.
 * An empty Domain or CertificateArn default fails that check, so the
 * template default is a placeholder the condition treats as unset.
 * `example.com` is not a domain this stack creates.
 */
export const COGNITO_CUSTOM_DOMAIN_DISABLED = "disabled.example.com";

/** Account 000000000000 keeps this from naming a real certificate. */
export const COGNITO_CUSTOM_CERTIFICATE_DISABLED =
  "arn:aws:acm:us-east-1:000000000000:certificate/disabled";

/** True for an empty value or the disabled placeholder. */
export function cognitoCustomValueUnset(
  value: string,
  disabled: string
): cdk.ICfnConditionExpression {
  return cdk.Fn.conditionOr(
    cdk.Fn.conditionEquals(value, ""),
    cdk.Fn.conditionEquals(value, disabled)
  );
}
