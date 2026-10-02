import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as lambdaEventSources from "aws-cdk-lib/aws-lambda-event-sources";
import * as ses from "aws-cdk-lib/aws-ses";
import * as sns from "aws-cdk-lib/aws-sns";
import * as snsSubs from "aws-cdk-lib/aws-sns-subscriptions";
import * as sqs from "aws-cdk-lib/aws-sqs";
import { PARSE_TIMEOUTS } from "./shared-contracts";
import { sesSendFromDomainStatement } from "./ses-send";

export interface OutreachEvents {
  readonly outreachSendingIdentity: ses.CfnEmailIdentity;
}

export function defineOutreachEvents(
  scope: cdk.Stack,
  adminFn: lambda.Function,
  sharedEncryptionKey: kms.IKey,
  outreachSendingDomain: cdk.CfnParameter,
): OutreachEvents {
  const outreachEventsDlq = new sqs.Queue(scope, "SiutindeiOutreachEventsDlq", {
    queueName: "lxsoftware-admin-siutindei-outreach-events-dlq",
    encryption: sqs.QueueEncryption.KMS,
    encryptionMasterKey: sharedEncryptionKey,
    retentionPeriod: cdk.Duration.days(14),
  });
  // Lambda rejects an SQS event source whose visibility timeout is shorter
  // than the function timeout; AWS recommends six times the function
  // timeout so a slow batch is not redelivered while still in flight.
  const outreachEventsQueue = new sqs.Queue(scope, "SiutindeiOutreachEventsQueue", {
    queueName: "lxsoftware-admin-siutindei-outreach-events",
    visibilityTimeout: cdk.Duration.seconds(
      PARSE_TIMEOUTS.lambdaTimeoutSeconds * 6
    ),
    encryption: sqs.QueueEncryption.KMS,
    encryptionMasterKey: sharedEncryptionKey,
    deadLetterQueue: { queue: outreachEventsDlq, maxReceiveCount: 5 },
  });
  const outreachEventsTopic = new sns.Topic(scope, "SiutindeiOutreachEventsTopic", {
    topicName: "lxsoftware-admin-siutindei-outreach-events",
    masterKey: sharedEncryptionKey,
  });
  outreachEventsTopic.addToResourcePolicy(
    new iam.PolicyStatement({
      principals: [new iam.ServicePrincipal("ses.amazonaws.com")],
      actions: ["sns:Publish"],
      resources: [outreachEventsTopic.topicArn],
      conditions: {
        StringEquals: { "AWS:SourceAccount": scope.account },
      },
    })
  );
  // SES event destinations must GenerateDataKey on a CMK-encrypted topic.
  sharedEncryptionKey.addToResourcePolicy(
    new iam.PolicyStatement({
      sid: "AllowSesOutreachEventEncryption",
      principals: [new iam.ServicePrincipal("ses.amazonaws.com")],
      actions: ["kms:Decrypt", "kms:GenerateDataKey*"],
      resources: ["*"],
      conditions: {
        StringEquals: { "aws:SourceAccount": scope.account },
      },
    })
  );
  outreachEventsTopic.addSubscription(new snsSubs.SqsSubscription(outreachEventsQueue));
  const outreachConfigSet = new ses.ConfigurationSet(scope, "SiutindeiOutreachConfigSet", {
    configurationSetName: "lxsoftware-admin-siutindei-outreach",
  });
  outreachConfigSet.addEventDestination("OutreachSesEvents", {
    destination: ses.EventDestination.snsTopic(outreachEventsTopic),
    events: [
      ses.EmailSendingEvent.BOUNCE,
      ses.EmailSendingEvent.COMPLAINT,
      ses.EmailSendingEvent.REJECT,
    ],
  });
  const newsletterConfigSet = new ses.ConfigurationSet(scope, "SiutindeiNewsletterConfigSet", {
    configurationSetName: "lxsoftware-admin-siutindei-newsletter",
  });
  newsletterConfigSet.addEventDestination("NewsletterSesEvents", {
    destination: ses.EventDestination.snsTopic(outreachEventsTopic),
    events: [
      ses.EmailSendingEvent.BOUNCE,
      ses.EmailSendingEvent.COMPLAINT,
      ses.EmailSendingEvent.REJECT,
      ses.EmailSendingEvent.OPEN,
      ses.EmailSendingEvent.CLICK,
    ],
  });
  adminFn.addEventSource(
    new lambdaEventSources.SqsEventSource(outreachEventsQueue, {
      batchSize: 10,
      reportBatchItemFailures: true,
    })
  );
  const outreachSendingIdentity = new ses.CfnEmailIdentity(scope, "SiutindeiOutreachSendingIdentity", {
    emailIdentity: outreachSendingDomain.valueAsString,
    dkimAttributes: { signingEnabled: true },
    mailFromAttributes: {
      mailFromDomain: cdk.Fn.join(".", ["mail", outreachSendingDomain.valueAsString]),
      behaviorOnMxFailure: "USE_DEFAULT_VALUE",
    },
  });
  adminFn.addToRolePolicy(sesSendFromDomainStatement(outreachSendingDomain.valueAsString));
  adminFn.addToRolePolicy(
    new iam.PolicyStatement({
      actions: ["ses:GetEmailIdentity"],
      resources: [
        cdk.Stack.of(scope).formatArn({
          service: "ses",
          resource: "identity",
          resourceName: outreachSendingDomain.valueAsString,
        }),
      ],
    })
  );
  return { outreachSendingIdentity };
}
