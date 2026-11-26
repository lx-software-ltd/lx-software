import * as cdk from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";

/**
 * CloudFormation Validate resolves parameter defaults before Conditions.
 * An empty DomainName or CertificateArn default fails that check, so the
 * template default is a placeholder the condition treats as unset.
 * `example.com` is not a domain this stack creates.
 */
export const API_CUSTOM_DOMAIN_DISABLED = "disabled.example.com";

/** Account 000000000000 keeps this from naming a real certificate. */
export const API_CUSTOM_CERTIFICATE_DISABLED =
  "arn:aws:acm:ap-southeast-1:000000000000:certificate/disabled";

/** True for an empty value or the disabled placeholder. */
function customValueUnset(value: string, disabled: string): cdk.ICfnConditionExpression {
  return cdk.Fn.conditionOr(
    cdk.Fn.conditionEquals(value, ""),
    cdk.Fn.conditionEquals(value, disabled),
  );
}

/**
 * Regional custom domain for the admin HTTP API, same shape as
 * findingalpha's `api.<domain>`: TLS 1.2 in this region, mapped to the
 * `$default` stage with no path prefix. When the domain is on, the
 * execute-api endpoint is disabled.
 */
export function defineApiDomain(
  scope: cdk.Stack,
  httpApi: apigwv2.HttpApi,
  name: cdk.CfnParameter,
  certificateArn: cdk.CfnParameter,
): { readonly useApiCustomDomain: cdk.CfnCondition; readonly url: string } {
  const useApiCustomDomain = new cdk.CfnCondition(scope, "UseApiCustomDomain", {
    expression: cdk.Fn.conditionAnd(
      cdk.Fn.conditionNot(customValueUnset(name.valueAsString, API_CUSTOM_DOMAIN_DISABLED)),
      cdk.Fn.conditionNot(
        customValueUnset(certificateArn.valueAsString, API_CUSTOM_CERTIFICATE_DISABLED),
      ),
    ),
  });
  const domain = new apigwv2.CfnDomainName(scope, "ApiCustomDomain", {
    domainName: name.valueAsString,
    domainNameConfigurations: [
      {
        certificateArn: certificateArn.valueAsString,
        endpointType: "REGIONAL",
        securityPolicy: "TLS_1_2",
      },
    ],
  });
  domain.cfnOptions.condition = useApiCustomDomain;
  const stage = httpApi.defaultStage?.node.defaultChild as apigwv2.CfnStage;
  const mapping = new apigwv2.CfnApiMapping(scope, "ApiCustomDomainMapping", {
    apiId: httpApi.apiId,
    domainName: domain.ref,
    stage: "$default",
  });
  mapping.cfnOptions.condition = useApiCustomDomain;
  // The mapping names the stage as "$default" and does not reference the stage resource.
  mapping.node.addDependency(stage);
  new cdk.CfnOutput(scope, "ApiCustomDomainTarget", {
    value: domain.attrRegionalDomainName,
    condition: useApiCustomDomain,
    description:
      "Regional API Gateway hostname. The api DNS record points here and stays DNS-only.",
  });
  const url = cdk.Fn.join("", ["https://", name.valueAsString]);
  new cdk.CfnOutput(scope, "ApiCustomDomainUrl", {
    value: url,
    condition: useApiCustomDomain,
  });
  return { useApiCustomDomain, url };
}
