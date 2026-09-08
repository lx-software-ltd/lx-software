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
    const publicMirrors = routes.filter((r) =>
      String(r.Properties?.RouteKey).includes(" /public/")
    );
    expect(publicMirrors.length).toBeGreaterThan(0);
    for (const route of publicMirrors) {
      expect(String(route.Properties?.RouteKey)).toMatch(/^GET /);
      expect(route.Properties?.AuthorizationType).toBe("CUSTOM");
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
  test("the SES send statement is scoped to the board mail identity, not *", () => {
    const [policy, ...rest] = findPoliciesByConstructId("SiutindeiBoardMailSendPolicy");
    expect(policy).toBeDefined();
    expect(rest).toHaveLength(0);

    const sendStatements = policyStatements(policy).filter((s) =>
      asArray<string>(s.Action).includes("ses:SendEmail")
    );
    expect(sendStatements).toHaveLength(1);

    const resources = asArray(sendStatements[0].Resource);
    expect(resources).toHaveLength(1);
    expect(resources[0]).not.toBe("*");
    // formatArn() emits a Fn::Join whose literal pieces include the
    // `:identity/` resource segment followed by the BoardMailDomain parameter.
    const serialized = JSON.stringify(resources[0]);
    expect(serialized).toContain(":ses:");
    expect(serialized).toContain(":identity/");
    expect(serialized).toContain('"Ref":"BoardMailDomain"');
  });

  test.each([
    ["AdminOpenRouterSecretPolicy", "HasOpenRouterSecret"],
    ["AdminSiutindeiDataApiPolicy", "HasSiutindeiDataApi"],
    ["SiutindeiBoardMailSendPolicy", "HasBoardMailSending"],
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
