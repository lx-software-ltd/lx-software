import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { LxsoftwareStack } from "../lib/lxsoftware-stack";

type CfnResource = {
  Type: string;
  Properties?: Record<string, any>;
  Condition?: string;
  DependsOn?: string | string[];
  UpdateReplacePolicy?: string;
  DeletionPolicy?: string;
};

/**
 * Synthesize the admin backend stack once for the whole file. The App is
 * built the same way as `bin/app.ts` (explicit env, no lookups) but with
 * asset bundling disabled so the test never needs Docker or AWS credentials.
 */
function synthStack(): Template {
  const app = new cdk.App({
    context: {
      "aws:cdk:bundling-stacks": [],
    },
  });
  const stack = new LxsoftwareStack(app, "lxsoftware", {
    env: { account: "123456789012", region: "ap-southeast-1" },
  });
  return Template.fromStack(stack);
}

let template: Template;
let resources: Record<string, CfnResource>;

beforeAll(() => {
  template = synthStack();
  resources = template.toJSON().Resources as Record<string, CfnResource>;
});

function resourcesOfType(type: string): Record<string, CfnResource> {
  return Object.fromEntries(
    Object.entries(resources).filter(([, r]) => r.Type === type)
  );
}

function policyStatements(policy: CfnResource): Record<string, any>[] {
  const statements = policy.Properties?.PolicyDocument?.Statement;
  return Array.isArray(statements) ? statements : [];
}

function asArray<T>(value: T | T[] | undefined): T[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

/** Find `AWS::IAM::Policy` resources whose logical id starts with a construct id. */
function findPoliciesByConstructId(constructId: string): CfnResource[] {
  return Object.entries(resourcesOfType("AWS::IAM::Policy"))
    .filter(([logicalId]) => logicalId.startsWith(constructId))
    .map(([, r]) => r);
}

describe("HTTP API routes", () => {
  const publicRouteKeys = new Set([
    "GET /health",
    // Meta verify handshake + HMAC-signed webhook deliveries; the handler
    // validates hub.verify_token / X-Hub-Signature-256 itself.
    "GET /webhooks/meta",
    "POST /webhooks/meta",
    "GET /webhooks/meta/siutindei",
    "POST /webhooks/meta/siutindei",
    // RFC 8058 one-click / browser unsubscribe; HMAC in the token, no JWT.
    "GET /public/outreach/unsubscribe/{token}",
    "POST /public/outreach/unsubscribe/{token}",
    "POST /public/newsletter/subscribe",
    "GET /public/newsletter/confirm/{token}",
    "GET /public/newsletter/unsubscribe/{token}",
    "POST /public/newsletter/unsubscribe/{token}",
  ]);

  test("only the health check and Meta webhook routes lack an authorizer", () => {
    const routes = Object.values(resourcesOfType("AWS::ApiGatewayV2::Route"));
    expect(routes.length).toBeGreaterThan(50);

    const unauthenticated = routes
      .filter((r) => {
        const authType = r.Properties?.AuthorizationType;
        return authType === undefined || authType === "NONE";
      })
      .map((r) => r.Properties?.RouteKey as string)
      .sort();

    expect(unauthenticated).toEqual([...publicRouteKeys].sort());
  });

  test("every other route uses a JWT or Lambda (CUSTOM) authorizer with an authorizer id", () => {
    const routes = Object.values(resourcesOfType("AWS::ApiGatewayV2::Route"));
    for (const route of routes) {
      const key = route.Properties?.RouteKey as string;
      if (publicRouteKeys.has(key)) continue;
      expect(["JWT", "CUSTOM"]).toContain(route.Properties?.AuthorizationType);
      expect(route.Properties?.AuthorizerId).toBeDefined();
    }
  });

  test("/public/* mirrors are GET-only and use the API key (CUSTOM) authorizer", () => {
    const routes = Object.values(resourcesOfType("AWS::ApiGatewayV2::Route"));
    const publicMirrors = routes.filter((r) => {
      const key = String(r.Properties?.RouteKey);
      return (
        key.includes(" /public/") &&
        !key.includes("/public/outreach/unsubscribe/") &&
        !key.includes("/public/newsletter/")
      );
    });
    expect(publicMirrors.length).toBeGreaterThan(0);
    for (const route of publicMirrors) {
      expect(String(route.Properties?.RouteKey)).toMatch(/^GET /);
      expect(route.Properties?.AuthorizationType).toBe("CUSTOM");
    }
  });

  test("AWS usage JSON and PDF routes are JWT-protected", () => {
    const routes = Object.values(resourcesOfType("AWS::ApiGatewayV2::Route"));
    const keys = routes.map((r) => r.Properties?.RouteKey as string);
    expect(keys).toEqual(expect.arrayContaining(["GET /aws/usage", "GET /aws/usage.pdf"]));
    for (const key of ["GET /aws/usage", "GET /aws/usage.pdf"]) {
      const route = routes.find((r) => r.Properties?.RouteKey === key);
      expect(route?.Properties?.AuthorizationType).toBe("JWT");
      expect(route?.Properties?.AuthorizerId).toBeDefined();
    }
  });
});

describe("HTTP API stage throttling", () => {
  test("the Meta webhook routes are throttled independently of the stage default", () => {
    template.hasResourceProperties("AWS::ApiGatewayV2::Stage", {
      StageName: "$default",
      RouteSettings: Match.objectLike({
        "POST /webhooks/meta": {
          ThrottlingRateLimit: 10,
          ThrottlingBurstLimit: 20,
        },
        "GET /webhooks/meta": {
          ThrottlingRateLimit: 10,
          ThrottlingBurstLimit: 20,
        },
        "POST /webhooks/meta/siutindei": {
          ThrottlingRateLimit: 10,
          ThrottlingBurstLimit: 20,
        },
        "GET /webhooks/meta/siutindei": {
          ThrottlingRateLimit: 10,
          ThrottlingBurstLimit: 20,
        },
      }),
    });
  });

  test("the stage has a conservative default throttle", () => {
    template.hasResourceProperties("AWS::ApiGatewayV2::Stage", {
      StageName: "$default",
      DefaultRouteSettings: {
        ThrottlingRateLimit: 50,
        ThrottlingBurstLimit: 100,
      },
    });
  });

  test("the default stage waits for Meta webhook routes before RouteSettings", () => {
    const [, stage] = Object.entries(resourcesOfType("AWS::ApiGatewayV2::Stage")).find(
      ([, r]) => r.Properties?.StageName === "$default"
    )!;
    const webhookRouteIds = Object.entries(resourcesOfType("AWS::ApiGatewayV2::Route"))
      .filter(([, r]) => String(r.Properties?.RouteKey).includes("/webhooks/meta"))
      .map(([id]) => id);
    expect(webhookRouteIds).toHaveLength(4);
    const dependsOn = asArray<string>(stage.DependsOn);
    for (const id of webhookRouteIds) {
      expect(dependsOn).toContain(id);
    }
  });

  test("access logging on the default stage is preserved", () => {
    template.hasResourceProperties("AWS::ApiGatewayV2::Stage", {
      StageName: "$default",
      AccessLogSettings: Match.objectLike({
        DestinationArn: Match.anyValue(),
        Format: Match.stringLikeRegexp("routeKey"),
      }),
    });
  });
});

describe("EventBridge Scheduler wiring", () => {
  test("every schedule invokes its target through an IAM role", () => {
    const schedules = Object.values(resourcesOfType("AWS::Scheduler::Schedule"));
    expect(schedules.length).toBeGreaterThan(0);
    for (const schedule of schedules) {
      expect(schedule.Properties?.Target?.RoleArn).toBeDefined();
      expect(schedule.Properties?.Target?.Arn).toBeDefined();
    }
  });

  test("no Lambda resource-policy statement is granted to scheduler.amazonaws.com", () => {
    const permissions = Object.values(resourcesOfType("AWS::Lambda::Permission"));
    const schedulerGrants = permissions.filter(
      (p) => p.Properties?.Principal === "scheduler.amazonaws.com"
    );
    expect(schedulerGrants).toEqual([]);
  });

  test("Siu Tin Dei board schedules use tenant names and boardKey", () => {
    const expected: Record<string, string> = {
      "lxsoftware-admin-siutindei-board-standup-morning": "board_meeting",
      "lxsoftware-admin-siutindei-board-standup-evening": "board_meeting",
      "lxsoftware-admin-siutindei-board-receivables-mirror": "board_receivables_mirror",
      "lxsoftware-admin-siutindei-board-dunning": "board_dunning",
      "lxsoftware-admin-siutindei-board-cache-refresh": "board_cache_refresh",
      "lxsoftware-admin-siutindei-board-staff-tick": "board_staff_tick",
      "lxsoftware-admin-siutindei-board-review-compile": "board_review_compile",
      "lxsoftware-admin-siutindei-board-review-send": "board_review_send",
      "lxsoftware-admin-siutindei-board-intel-crawl": "board_intel_crawl",
      "lxsoftware-admin-siutindei-board-intel-weekly": "board_intel_weekly",
      "lxsoftware-admin-siutindei-board-targets": "board_targets",
      "lxsoftware-admin-siutindei-board-content-plan": "board_content_plan",
      "lxsoftware-admin-siutindei-board-content-readout": "board_content_readout",
      "lxsoftware-admin-siutindei-data-api-ensure": "siutindei_data_api_ensure",
    };
    const schedules = Object.values(resourcesOfType("AWS::Scheduler::Schedule"));
    const byName = Object.fromEntries(
      schedules
        .filter((s) => typeof s.Properties?.Name === "string")
        .map((s) => [s.Properties?.Name as string, s])
    );
    expect(Object.keys(byName).sort()).toEqual(Object.keys(expected).sort());
    for (const [name, internal] of Object.entries(expected)) {
      const input = JSON.stringify(byName[name].Properties?.Target?.Input ?? "");
      expect(input).toContain(internal);
      expect(input).toContain("siuTinDei");
    }
  });
});

describe("Admin Lambda IAM policies", () => {
  /**
   * Every SES send grant is `Resource: *` constrained by `ses:FromAddress`
   * on one domain parameter. SES authorizes SendRawEmail against the mailbox
   * identity, so identity-ARN resource lists deny in production.
   */
  function expectSesSendScopedToDomain(statement: Record<string, any>, domainParam: string): void {
    expect(asArray<string>(statement.Action)).toEqual(
      expect.arrayContaining(["ses:SendEmail", "ses:SendRawEmail"])
    );
    expect(asArray(statement.Resource)).toEqual(["*"]);
    const patterns = asArray(statement.Condition?.StringLike?.["ses:FromAddress"]);
    expect(patterns.length).toBeGreaterThanOrEqual(1);
    const serialized = JSON.stringify(patterns);
    expect(serialized).toContain("*@");
    expect(serialized).toContain(`"Ref":"${domainParam}"`);
    expect(serialized).not.toContain("*@*");
  }

  function sendStatementsOf(policy: CfnResource): Record<string, any>[] {
    return policyStatements(policy).filter((s) => asArray<string>(s.Action).includes("ses:SendEmail"));
  }

  test("statement parse notify may only send from the inbound mail domain", () => {
    const [policy, ...rest] = findPoliciesByConstructId("StatementParseNotifySendPolicy");
    expect(policy).toBeDefined();
    expect(rest).toHaveLength(0);
    const sends = sendStatementsOf(policy);
    expect(sends).toHaveLength(1);
    expectSesSendScopedToDomain(sends[0], "InboundMailDomain");
  });

  test("board mail may only send from the board mail domain and can read its SES health", () => {
    const [policy, ...rest] = findPoliciesByConstructId("SiutindeiBoardMailSendPolicy");
    expect(policy).toBeDefined();
    expect(rest).toHaveLength(0);
    const sends = sendStatementsOf(policy);
    expect(sends).toHaveLength(1);
    expectSesSendScopedToDomain(sends[0], "SiutindeiBoardMailDomain");

    const statements = policyStatements(policy);
    const identityRead = statements.find((s) => asArray<string>(s.Action).includes("ses:GetEmailIdentity"));
    expect(identityRead).toBeDefined();
    expect(JSON.stringify(identityRead?.Resource)).toContain('"Ref":"SiutindeiBoardMailDomain"');
    const accountRead = statements.find((s) => asArray<string>(s.Action).includes("ses:GetAccount"));
    expect(accountRead).toBeDefined();
    // No statement in this policy hands out ses:* or admin actions.
    for (const s of statements) {
      for (const action of asArray<string>(s.Action)) {
        expect(action).not.toBe("ses:*");
        expect(action.startsWith("ses:")).toBe(true);
      }
    }
  });

  test("outreach may only send from the outreach domain", () => {
    const rolePolicies = Object.values(resourcesOfType("AWS::IAM::Policy"));
    const outreachSends = rolePolicies
      .flatMap((p) => sendStatementsOf(p))
      .filter((s) => JSON.stringify(s.Condition ?? {}).includes('"Ref":"SiutindeiBoardOutreachSendingDomain"'));
    expect(outreachSends).toHaveLength(1);
    expectSesSendScopedToDomain(outreachSends[0], "SiutindeiBoardOutreachSendingDomain");

    // Nothing anywhere grants SES sending without a FromAddress condition.
    const unconditional = rolePolicies
      .flatMap((p) => sendStatementsOf(p))
      .filter((s) => !s.Condition?.StringLike?.["ses:FromAddress"]);
    expect(unconditional).toEqual([]);
  });

  test.each([
    ["AdminOpenRouterSecretPolicy", "HasOpenRouterSecret"],
    ["AdminSiutindeiDataApiPolicy", "HasSiutindeiDataApi"],
    ["SiutindeiBoardMailSendPolicy", "HasSiutindeiBoardMailSending"],
  ])("%s keeps its %s condition", (constructId, conditionName) => {
    const policies = findPoliciesByConstructId(constructId);
    expect(policies).toHaveLength(1);
    expect(policies[0].Condition).toBe(conditionName);
    expect(template.toJSON().Conditions[conditionName]).toBeDefined();
  });

  describe("SiutindeiBoardAwsReadPolicy", () => {
    let statements: Record<string, any>[];

    beforeAll(() => {
      const policies = findPoliciesByConstructId("SiutindeiBoardAwsReadPolicy");
      expect(policies).toHaveLength(1);
      statements = policyStatements(policies[0]);
    });

    test("has no cognito-idp statement on *", () => {
      const cognitoOnStar = statements.filter(
        (s) =>
          asArray<string>(s.Action).some((a) => a.startsWith("cognito-idp:")) &&
          asArray(s.Resource).includes("*")
      );
      expect(cognitoOnStar).toEqual([]);
    });

    test("scopes cognito-idp:DescribeUserPool to this stack's user pool", () => {
      const cognito = statements.filter((s) =>
        asArray<string>(s.Action).includes("cognito-idp:DescribeUserPool")
      );
      expect(cognito).toHaveLength(1);
      expect(asArray<string>(cognito[0].Action)).toEqual(["cognito-idp:DescribeUserPool"]);
      const [resource] = asArray<Record<string, any>>(cognito[0].Resource);
      expect(resource).toEqual({
        "Fn::GetAtt": [expect.stringMatching(/UserPool/), "Arn"],
      });
      const pools = Object.keys(resourcesOfType("AWS::Cognito::UserPool"));
      expect(pools).toContain(resource["Fn::GetAtt"][0]);
    });

    test("scopes securityhub:GetFindings to the regional default hub", () => {
      const hub = statements.filter((s) =>
        asArray<string>(s.Action).includes("securityhub:GetFindings")
      );
      expect(hub).toHaveLength(1);
      expect(asArray<string>(hub[0].Action)).toEqual(["securityhub:GetFindings"]);
      const serialized = JSON.stringify(hub[0].Resource);
      expect(serialized).not.toBe('"*"');
      expect(serialized).toContain(":securityhub:ap-southeast-1:123456789012:hub/default");
    });

    test("scopes access-analyzer:ListFindings to analyzer ARNs; ListAnalyzers alone stays on *", () => {
      const listFindings = statements.filter((s) =>
        asArray<string>(s.Action).includes("access-analyzer:ListFindings")
      );
      expect(listFindings).toHaveLength(1);
      expect(asArray<string>(listFindings[0].Action)).toEqual(["access-analyzer:ListFindings"]);
      expect(JSON.stringify(listFindings[0].Resource)).toContain(
        ":access-analyzer:ap-southeast-1:123456789012:analyzer/*"
      );

      const listAnalyzers = statements.filter((s) =>
        asArray<string>(s.Action).includes("access-analyzer:ListAnalyzers")
      );
      expect(listAnalyzers).toHaveLength(1);
      expect(asArray<string>(listAnalyzers[0].Action)).toEqual(["access-analyzer:ListAnalyzers"]);
    });

    test("only the account-scoped read APIs remain on *", () => {
      const onStar = statements
        .filter((s) => asArray(s.Resource).includes("*"))
        .flatMap((s) => asArray<string>(s.Action))
        .sort();
      expect(onStar).toEqual(
        [
          "access-analyzer:ListAnalyzers",
          "ce:GetCostAndUsage",
          "cloudwatch:DescribeAlarms",
          "cloudwatch:GetMetricData",
          "health:DescribeEvents",
        ].sort()
      );
    });
  });
});

describe("Executive Board placeholder secrets", () => {
  const reservedNames = [
    "lxsoftware-admin-github-read-token",
    "lxsoftware-admin-search-api-key",
    "lxsoftware-admin-meta-board-token",
    "lxsoftware-admin-meta-app-secret",
    "lxsoftware-admin-app-store-connect-key",
    "lxsoftware-admin-google-play-sa",
    "lxsoftware-admin-google-analytics-sa",
  ];
  const siutindeiNames = [
    "lxsoftware-admin-siutindei-board-github-token",
    "lxsoftware-admin-siutindei-board-search-api-key",
    "lxsoftware-admin-siutindei-board-meta-token",
    "lxsoftware-admin-siutindei-board-meta-app-secret",
    "lxsoftware-admin-siutindei-board-app-store-connect-key",
    "lxsoftware-admin-siutindei-board-google-play-sa",
    "lxsoftware-admin-siutindei-board-google-analytics-sa",
    "lxsoftware-admin-siutindei-board-google-places-key",
    "lxsoftware-admin-siutindei-board-link-signing-key",
  ];

  const removedParameters = [
    "GitHubReadTokenSecretArn",
    "SearchApiKeySecretArn",
    "MetaBoardTokenSecretArn",
    "MetaAppSecretSecretArn",
    "AppStoreConnectKeySecretArn",
    "GooglePlayServiceAccountSecretArn",
    "GoogleAnalyticsServiceAccountSecretArn",
  ];

  function secretsNamed(names: string[]): CfnResource[] {
    return Object.values(resourcesOfType("AWS::SecretsManager::Secret")).filter((r) =>
      names.includes(r.Properties?.Name as string)
    );
  }

  function expectRetainedPlaceholders(
    secrets: CfnResource[],
    tenant: string,
    purpose: string,
  ) {
    for (const secret of secrets) {
      expect(secret.Properties?.GenerateSecretString).toBeDefined();
      expect(secret.UpdateReplacePolicy).toBe("Retain");
      expect(secret.DeletionPolicy).toBe("Retain");
      const tags = asArray<{ Key: string; Value: string }>(secret.Properties?.Tags);
      expect(tags).toEqual(
        expect.arrayContaining([
          { Key: "lxsoftware:tenant", Value: tenant },
          { Key: "lxsoftware:purpose", Value: purpose },
        ]),
      );
    }
  }

  test("keeps the deployed LX Software board secrets and imports the Siu Tin Dei set", () => {
    const reserved = secretsNamed(reservedNames);
    const siutindei = secretsNamed(siutindeiNames);
    expect(reserved.map((s) => s.Properties?.Name).sort()).toEqual([...reservedNames].sort());
    expect(siutindei).toEqual([]);
    expectRetainedPlaceholders(reserved, "lxsoftware", "lxsoftware-executive-board");
  });

  test("the JSON store / analytics secrets include a generated private-key field", () => {
    const byName = Object.fromEntries(
      secretsNamed(reservedNames).map((s) => [s.Properties?.Name as string, s])
    );
    expect(byName["lxsoftware-admin-app-store-connect-key"].Properties?.GenerateSecretString).toEqual(
      expect.objectContaining({
        GenerateStringKey: "privateKey",
        SecretStringTemplate: expect.stringContaining("keyId"),
      })
    );
    for (const name of [
      "lxsoftware-admin-google-play-sa",
      "lxsoftware-admin-google-analytics-sa",
    ]) {
      expect(byName[name].Properties?.GenerateSecretString).toEqual(
        expect.objectContaining({
          GenerateStringKey: "private_key",
          SecretStringTemplate: expect.stringContaining("client_email"),
        })
      );
    }
  });

  test("removed CfnParameters no longer exist", () => {
    const parameters = template.toJSON().Parameters as Record<string, unknown>;
    for (const name of removedParameters) {
      expect(parameters[name]).toBeUndefined();
    }
  });

  test("AdminApiFn can GetSecretValue on the Siu Tin Dei board secrets only", () => {
    const reservedIds = Object.entries(resourcesOfType("AWS::SecretsManager::Secret"))
      .filter(([, r]) => reservedNames.includes(r.Properties?.Name as string))
      .map(([id]) => id);

    const getSecretStatements = Object.values(resourcesOfType("AWS::IAM::Policy"))
      .flatMap((policy) => policyStatements(policy))
      .filter((s) => asArray<string>(s.Action).includes("secretsmanager:GetSecretValue"));

    const serialized = JSON.stringify(getSecretStatements);
    for (const name of siutindeiNames) {
      expect(serialized).toContain(name);
    }
    for (const logicalId of reservedIds) {
      expect(serialized).not.toContain(logicalId);
    }
  });
});

describe("Siu Tin Dei parameter naming", () => {
  const boardFamily = /Board|Outreach|Meta|Ga4|Gtm|AppStoreConnect|GooglePlay/;
  const retiredUnprefixed = [
    "BoardStaffEnabled",
    "BoardToolsEnabled",
    "BoardMailSendingEnabled",
    "BoardGitHubRepo",
    "BoardMailDomain",
    "BoardChatModel",
    "BoardMeetingModel",
    "BoardDeepDiveModel",
    "BoardAwsStackPrefix",
    "BoardAwsLambdaNames",
    "MetaVerifyToken",
    "MetaPageId",
    "MetaIgUserId",
    "MetaWaPhoneNumberId",
    "MetaWabaId",
    "MetaAdAccountId",
    "Ga4PropertyIds",
    "GtmContainers",
    "AppStoreConnectAppId",
    "AppStoreConnectVendorNumber",
    "GooglePlayPackageName",
    "OutreachSendingDomain",
    "OutreachFromLocalPart",
  ];

  test("board-scoped CfnParameters use the SiutindeiBoard prefix", () => {
    const parameters = Object.keys(template.toJSON().Parameters as Record<string, unknown>);
    const boardScoped = parameters.filter((name) => boardFamily.test(name));
    expect(boardScoped.length).toBeGreaterThan(0);
    for (const name of boardScoped) {
      expect(name).toMatch(/^SiutindeiBoard/);
    }
  });

  test("retired unprefixed board parameter names are absent", () => {
    const parameters = template.toJSON().Parameters as Record<string, unknown>;
    for (const name of retiredUnprefixed) {
      expect(parameters[name]).toBeUndefined();
    }
  });

  test("production.json lxsoftware keys name existing CfnParameters", () => {
    const raw = fs.readFileSync(
      path.join(__dirname, "../params/production.json"),
      "utf8",
    );
    const file = JSON.parse(raw) as Record<string, string>;
    const parameters = template.toJSON().Parameters as Record<string, unknown>;
    const lxsoftwareKeys = Object.keys(file).filter((key) =>
      key.startsWith("lxsoftware:"),
    );
    expect(lxsoftwareKeys).toContain("lxsoftware:SiutindeiBoardStaffEnabled");
    expect(file["lxsoftware:SiutindeiBoardStaffEnabled"]).toBe("true");
    for (const key of lxsoftwareKeys) {
      expect(parameters[key.slice("lxsoftware:".length)]).toBeDefined();
    }
  });
});

describe("Siu Tin Dei board mail outputs", () => {
  test("inbound mailbox uses the tenant-prefixed export", () => {
    const outputs = template.toJSON().Outputs as Record<
      string,
      { Export?: { Name?: string } }
    >;
    expect(outputs.SiutindeiBoardMailInboundAddress?.Export?.Name).toBe(
      "lxsoftware-SiutindeiBoardMailInboundAddress"
    );
    expect(outputs.BoardMailInboundAddress).toBeUndefined();
  });
});

describe("shared inbound SES receipt rule set", () => {
  test("hosts hillmarton, morrison, LX Software billing, siutindei-board, and Evolve Sprouts invoice rules", () => {
    const ruleSets = Object.values(resourcesOfType("AWS::SES::ReceiptRuleSet"));
    expect(ruleSets).toHaveLength(1);
    expect(ruleSets[0].Properties?.RuleSetName).toBe("lxsoftware-inbound-mail");

    const rules = Object.values(resourcesOfType("AWS::SES::ReceiptRule"));
    const serialized = JSON.stringify(rules);
    expect(serialized).toContain("32-hillmarton");
    expect(serialized).toContain("the-morrison");
    expect(serialized).toContain("billing");
    expect(serialized).toContain("siutindei-board");
    expect(serialized).toContain("inbound-raw/hillmarton/");
    expect(serialized).toContain("inbound-raw/morrison/");
    expect(serialized).toContain("inbound-raw/lx-software/");

    const lambdaEnv = JSON.stringify(template.toJSON());
    expect(lambdaEnv).toContain("INBOUND_STATEMENT_MAILBOXES");
    expect(lambdaEnv).toContain("lxSoftware");
    expect(lambdaEnv).toContain("expenditure");

    const invoiceRule = rules.find(
      (r) => r.Properties?.Rule?.Name === "evolvesprouts-inbound-invoice-email-rule"
    );
    expect(invoiceRule).toBeDefined();
    expect(invoiceRule?.Properties?.RuleSetName).toBeDefined();
    expect(invoiceRule?.Properties?.Rule?.Enabled).toBe(true);
    expect(invoiceRule?.Properties?.Rule?.Recipients).toEqual([
      { Ref: "EvolvesproutsInboundInvoiceRecipient" },
    ]);
    const s3Action = invoiceRule?.Properties?.Rule?.Actions?.[0]?.S3Action;
    expect(s3Action?.ObjectKeyPrefix).toBe("inbound-email/raw/");
    expect(JSON.stringify(s3Action?.BucketName)).toContain("evolvesprouts-assets");
    expect(JSON.stringify(s3Action?.TopicArn)).toContain(
      "evolvesprouts-inbound-invoice-email-events"
    );
    expect(JSON.stringify(s3Action?.IamRoleArn)).toContain(
      "EvolvesproutsInboundInvoiceReceiptRoleName"
    );
  });

  test("exports hillmarton, morrison, and LX Software billing inbound mailbox addresses", () => {
    const outputs = template.toJSON().Outputs as Record<
      string,
      { Export?: { Name?: string }; Description?: string }
    >;
    expect(outputs.InboundMailboxAddresshillmarton?.Export?.Name).toBe(
      "lxsoftware-InboundMailbox-hillmarton"
    );
    expect(outputs.InboundMailboxAddressmorrison?.Export?.Name).toBe(
      "lxsoftware-InboundMailbox-morrison"
    );
    expect(outputs.InboundMailboxAddressmorrison?.Description).toContain(
      "The Morrison"
    );
    expect(outputs.InboundMailboxAddresslxSoftware?.Export?.Name).toBe(
      "lxsoftware-InboundMailbox-lxSoftware"
    );
    expect(outputs.InboundMailboxAddresslxSoftware?.Description).toContain(
      "LX Software"
    );
    expect(outputs.InboundMailboxAddresslxSoftware?.Description).toContain(
      "billing@lx-software.com"
    );
  });

  test("activates the shared rule set on create and update", () => {
    const serialized = JSON.stringify(template.toJSON());
    expect(serialized).toContain("setActiveReceiptRuleSet");
    expect(serialized).toContain("lxsoftware-inbound-mail-active");
  });
});

describe("Board staff kill switches on both lambdas", () => {
  test("AdminApiFn and InboundStatementMailFn share BOARD_STAFF_ENABLED and mail flags", () => {
    const fns = Object.values(resourcesOfType("AWS::Lambda::Function"));
    const flagged = fns.filter((r) => {
      const env = r.Properties?.Environment?.Variables || {};
      return env.BOARD_STAFF_ENABLED && env.OUTREACH_SENDING_DOMAIN;
    });
    expect(flagged.length).toBeGreaterThanOrEqual(2);
    for (const fn of flagged) {
      const env = fn.Properties?.Environment?.Variables || {};
      expect(env.BOARD_STAFF_ENABLED).toBeDefined();
      expect(env.BOARD_TOOLS_ENABLED).toBeDefined();
      expect(env.BOARD_MAIL_SENDING_ENABLED).toBeDefined();
      expect(env.OUTREACH_SENDING_DOMAIN).toBeDefined();
      expect(env.OUTREACH_FROM_LOCAL_PART).toBeDefined();
    }
  });
});

describe("Siu Tin Dei Data API setup", () => {
  test("HasSiutindeiDataApi is cluster ARN only", () => {
    const cond = template.toJSON().Conditions.HasSiutindeiDataApi;
    const serialized = JSON.stringify(cond);
    expect(serialized).toContain("SiutindeiClusterArn");
    expect(serialized).not.toContain("SiutindeiDbSecretArn");
    expect(template.toJSON().Parameters.SiutindeiDbSecretName).toBeDefined();
  });

  test("enables the HTTP endpoint and applies receivables.sql when the cluster ARN is set", () => {
    const custom = Object.entries(resources).filter(
      ([, r]) =>
        r.Type === "Custom::AWS" || r.Type === "AWS::CloudFormation::CustomResource"
    );
    const enable = custom.find(([, r]) =>
      JSON.stringify(r.Properties ?? {}).includes("enableHttpEndpoint")
    );
    expect(enable).toBeDefined();
    expect(enable?.[1].Condition).toBe("HasSiutindeiDataApi");

    const schema = custom.find(
      ([id, r]) =>
        id.includes("ReceivablesSchema") &&
        r.Type === "AWS::CloudFormation::CustomResource"
    );
    expect(schema).toBeDefined();
    expect(schema?.[1].Condition).toBe("HasSiutindeiDataApi");
    // A provider that never answers must fail well inside the CI token's
    // one-hour lifetime instead of CloudFormation's default one-hour wait.
    expect(Number(schema?.[1].Properties?.ServiceTimeout)).toBe(900);
    const sqlOnlyHash = crypto
      .createHash("sha256")
      .update(
        fs.readFileSync(
          path.join(__dirname, "../../lambda/siutindei_schema/receivables.sql")
        )
      )
      .digest("hex")
      .slice(0, 16);
    expect(schema?.[1].Properties?.sqlHash).toEqual(expect.stringMatching(/^[0-9a-f]{16}$/));
    expect(schema?.[1].Properties?.sqlHash).not.toBe(sqlOnlyHash);

    const schemaFn = Object.entries(resourcesOfType("AWS::Lambda::Function")).find(
      ([id]) => id.includes("ReceivablesSchemaFn")
    );
    expect(schemaFn).toBeDefined();
    expect(schemaFn?.[1].Condition).toBe("HasSiutindeiDataApi");
    expect(schemaFn?.[1].Properties?.Timeout).toBe(180);
    expect(schemaFn?.[1].Properties?.MemorySize).toBe(256);

    const adminFn = Object.entries(resourcesOfType("AWS::Lambda::Function")).find(
      ([id]) => id.startsWith("AdminApiFn")
    );
    const secretEnv =
      adminFn?.[1].Properties?.Environment?.Variables?.SIUTINDEI_DB_SECRET_ARN;
    expect(secretEnv).toEqual({
      "Fn::If": ["HasSiutindeiDataApi", expect.anything(), ""],
    });
  });

  test("a Scheduler re-enables the HTTP endpoint; no EventBridge Rule targets the schema Lambda", () => {
    const rules = JSON.stringify(Object.values(resourcesOfType("AWS::Events::Rule")));
    expect(rules).not.toContain("ReceivablesSchemaFn");
    const schedules = Object.values(resourcesOfType("AWS::Scheduler::Schedule"));
    const ensure = schedules.find(
      (s) => s.Properties?.Name === "lxsoftware-admin-siutindei-data-api-ensure"
    );
    expect(ensure).toBeDefined();
    expect(ensure?.Condition).toBe("HasSiutindeiDataApi");
    expect(ensure?.Properties?.Target?.RoleArn).toBeDefined();
    expect(JSON.stringify(ensure?.Properties?.Target?.Input ?? "")).toContain(
      "siutindei_data_api_ensure"
    );
    const schemaFn = Object.keys(resourcesOfType("AWS::Lambda::Function")).find((id) =>
      id.includes("ReceivablesSchemaFn")
    );
    expect(JSON.stringify(ensure?.Properties?.Target?.Arn ?? "")).toContain(schemaFn);
  });

  test("CloudFormation invoke on the schema Lambda is limited to this account", () => {
    const permissions = Object.values(resourcesOfType("AWS::Lambda::Permission"));
    const cfnInvoke = permissions.find(
      (p) =>
        p.Properties?.Principal === "cloudformation.amazonaws.com" &&
        JSON.stringify(p.Properties?.FunctionName ?? "").includes("ReceivablesSchemaFn"),
    );
    expect(cfnInvoke).toBeDefined();
    expect(cfnInvoke?.Properties?.SourceAccount).toEqual({ Ref: "AWS::AccountId" });
    expect(cfnInvoke?.Properties?.Action).toBe("lambda:InvokeFunction");
  });
});

describe("Lambda service-principal permissions", () => {
  test("every AWS service invoke grant sets SourceArn or SourceAccount", () => {
    const permissions = Object.values(resourcesOfType("AWS::Lambda::Permission"));
    expect(permissions.length).toBeGreaterThan(0);
    for (const permission of permissions) {
      const principal = permission.Properties?.Principal;
      if (typeof principal !== "string" || !principal.endsWith(".amazonaws.com")) {
        continue;
      }
      expect(
        permission.Properties?.SourceArn || permission.Properties?.SourceAccount,
      ).toBeTruthy();
    }
  });
});

describe("SQS event sources on AdminApiFn", () => {
  test("every source queue's visibility timeout covers the function timeout", () => {
    const fns = resourcesOfType("AWS::Lambda::Function");
    const queues = resourcesOfType("AWS::SQS::Queue");
    const mappings = Object.values(resourcesOfType("AWS::Lambda::EventSourceMapping"));
    expect(mappings.length).toBeGreaterThanOrEqual(1);
    for (const mapping of mappings) {
      const fnRef = mapping.Properties?.FunctionName?.Ref as string;
      const queueRef = mapping.Properties?.EventSourceArn?.["Fn::GetAtt"]?.[0] as string;
      const fnTimeout = fns[fnRef]?.Properties?.Timeout as number;
      const visibility = queues[queueRef]?.Properties?.VisibilityTimeout as number;
      expect(fnTimeout).toBeGreaterThan(0);
      expect(visibility).toBeGreaterThanOrEqual(fnTimeout);
    }
  });
});

describe("Board SES configuration-set IAM and public CORS", () => {
  test("outreach and newsletter configuration sets exist and templates stay prefixed", () => {
    const configSets = Object.values(resourcesOfType("AWS::SES::ConfigurationSet")).map(
      (r) => r.Properties?.Name
    );
    expect(configSets).toEqual(
      expect.arrayContaining(["lxsoftware-admin-siutindei-outreach", "lxsoftware-admin-siutindei-newsletter"])
    );
    // Send grants are `Resource: *` + ses:FromAddress (see the IAM tests), which
    // already covers the configuration-set resource SendEmail checks.
    const serialized = JSON.stringify(template.toJSON());
    expect(serialized).toContain("template/lxsoftware-admin-siutindei-*");
    expect(serialized).toContain("ReportBatchItemFailures");
  });

  test("CORS origins include the PublicSiteOrigins parameter", () => {
    const serialized = JSON.stringify(template.toJSON());
    expect(serialized).toContain("PublicSiteOrigins");
    expect(serialized).toContain("lx-software.com");
  });
});
