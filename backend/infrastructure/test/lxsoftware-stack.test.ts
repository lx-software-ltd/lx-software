import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { LxsoftwareStack } from "../lib/lxsoftware-stack";

type CfnResource = {
  Type: string;
  Properties?: Record<string, any>;
  Condition?: string;
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
});

describe("Admin Lambda IAM policies", () => {
  test("the SES send statement is scoped to the board mail identity, not *", () => {
    const [policy, ...rest] = findPoliciesByConstructId("AdminBoardMailSendPolicy");
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
    ["AdminBoardMailSendPolicy", "HasBoardMailSending"],
  ])("%s keeps its %s condition", (constructId, conditionName) => {
    const policies = findPoliciesByConstructId(constructId);
    expect(policies).toHaveLength(1);
    expect(policies[0].Condition).toBe(conditionName);
    expect(template.toJSON().Conditions[conditionName]).toBeDefined();
  });

  describe("AdminBoardAwsReadPolicy", () => {
    let statements: Record<string, any>[];

    beforeAll(() => {
      const policies = findPoliciesByConstructId("AdminBoardAwsReadPolicy");
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
  const expectedNames = [
    "lxsoftware-admin-github-read-token",
    "lxsoftware-admin-search-api-key",
    "lxsoftware-admin-meta-board-token",
    "lxsoftware-admin-meta-app-secret",
    "lxsoftware-admin-app-store-connect-key",
    "lxsoftware-admin-google-play-sa",
    "lxsoftware-admin-google-analytics-sa",
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

  function boardSecrets(): CfnResource[] {
    return Object.values(resourcesOfType("AWS::SecretsManager::Secret")).filter((r) =>
      expectedNames.includes(r.Properties?.Name as string)
    );
  }

  test("CDK creates the seven named board secrets with generated dummy values", () => {
    const secrets = boardSecrets();
    expect(secrets.map((s) => s.Properties?.Name).sort()).toEqual([...expectedNames].sort());
    for (const secret of secrets) {
      expect(secret.Properties?.GenerateSecretString).toBeDefined();
      expect(secret.UpdateReplacePolicy).toBe("Retain");
      expect(secret.DeletionPolicy).toBe("Retain");
      const tags = asArray<{ Key: string; Value: string }>(secret.Properties?.Tags);
      expect(tags).toEqual(
        expect.arrayContaining([
          { Key: "lxsoftware:tenant", Value: "siutindei" },
          { Key: "lxsoftware:purpose", Value: "siutindei-executive-board" },
        ]),
      );
    }
  });

  test("the JSON store / analytics secrets include a generated private-key field", () => {
    const byName = Object.fromEntries(
      boardSecrets().map((s) => [s.Properties?.Name as string, s])
    );
    expect(byName["lxsoftware-admin-app-store-connect-key"].Properties?.GenerateSecretString).toEqual(
      expect.objectContaining({
        GenerateStringKey: "privateKey",
        SecretStringTemplate: expect.stringContaining("keyId"),
      })
    );
    expect(byName["lxsoftware-admin-google-play-sa"].Properties?.GenerateSecretString).toEqual(
      expect.objectContaining({
        GenerateStringKey: "private_key",
        SecretStringTemplate: expect.stringContaining("client_email"),
      })
    );
    expect(byName["lxsoftware-admin-google-analytics-sa"].Properties?.GenerateSecretString).toEqual(
      expect.objectContaining({
        GenerateStringKey: "private_key",
        SecretStringTemplate: expect.stringContaining("client_email"),
      })
    );
  });

  test("removed CfnParameters no longer exist", () => {
    const parameters = template.toJSON().Parameters as Record<string, unknown>;
    for (const name of removedParameters) {
      expect(parameters[name]).toBeUndefined();
    }
  });

  test("AdminApiFn can GetSecretValue on every board secret", () => {
    const secretLogicalIds = Object.entries(resourcesOfType("AWS::SecretsManager::Secret"))
      .filter(([, r]) => expectedNames.includes(r.Properties?.Name as string))
      .map(([id]) => id);

    const getSecretStatements = Object.values(resourcesOfType("AWS::IAM::Policy"))
      .flatMap((policy) => policyStatements(policy))
      .filter((s) => asArray<string>(s.Action).includes("secretsmanager:GetSecretValue"));

    const serialized = JSON.stringify(getSecretStatements);
    for (const logicalId of secretLogicalIds) {
      expect(serialized).toContain(logicalId);
    }
  });
});
