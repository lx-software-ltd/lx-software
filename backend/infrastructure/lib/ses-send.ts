import * as iam from "aws-cdk-lib/aws-iam";

/**
 * SES send grant restricted to one sending domain.
 *
 * SES authorizes `SendRawEmail` against `identity/<mailbox>` (not the verified
 * domain identity), and a display-name From is treated as yet another
 * identity, so identity-ARN resource lists AccessDenied in production while
 * unit tests pass. AWS's documented way to scope senders is `Resource: *`
 * plus the `ses:FromAddress` condition; `*` also covers the configuration-set
 * resource that `SendEmail` checks when a ConfigurationSetName is passed.
 */
export function sesSendFromDomainStatement(domain: string): iam.PolicyStatement {
  return new iam.PolicyStatement({
    actions: ["ses:SendEmail", "ses:SendRawEmail", "ses:SendBulkEmail"],
    resources: ["*"],
    conditions: {
      StringLike: {
        "ses:FromAddress": [`*@${domain}`, `*@${domain}>`],
      },
    },
  });
}
