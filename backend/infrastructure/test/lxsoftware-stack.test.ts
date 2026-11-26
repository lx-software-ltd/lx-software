import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import * as cognito from "aws-cdk-lib/aws-cognito";
import { Match, Template } from "aws-cdk-lib/assertions";
import {
  API_CUSTOM_CERTIFICATE_DISABLED,
  API_CUSTOM_DOMAIN_DISABLED,
} from "../lib/admin-api-domain";
import {
  COGNITO_CUSTOM_CERTIFICATE_DISABLED,
  COGNITO_CUSTOM_DOMAIN_DISABLED,
} from "../lib/cognito-custom-domain";
import { CheckovSuppressionAspect } from "../lib/constructs/checkov-suppressions";
import { LxsoftwareAdminWebStack } from "../lib/lxsoftware-admin-web-stack";
import { LxsoftwareStack } from "../lib/lxsoftware-stack";
import { PublicWebsiteStack } from "../lib/public-website-stack";

type CfnResource = {
  Type: string;
  Properties?: Record<string, any>;
  Condition?: string;
  DependsOn?: string | string[];
  UpdateReplacePolicy?: string;
  DeletionPolicy?: string;
  Metadata?: { checkov?: { skip?: { id: string }[] } };
};

function cloudFormationViolations(app: cdk.App): {
  ruleName: string;
  description: string;
  constructPath: string;
}[] {
  const assembly = app.synth();
  const report = JSON.parse(
    fs.readFileSync(path.join(assembly.directory, "validation-report.json"), "utf8")
  ) as {
    pluginReports?: {
      violations?: {
        ruleName: string;
        description: string;
        violatingConstructs?: { constructPath?: string }[];
      }[];
    }[];
  };
  return (report.pluginReports ?? []).flatMap((plugin) =>
    (plugin.violations ?? []).flatMap((violation) =>
      (violation.violatingConstructs ?? []).map((construct) => ({
        ruleName: violation.ruleName,
        description: violation.description,
        constructPath: construct.constructPath ?? "",
      }))
    )
  );
}

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
  cdk.Aspects.of(app).add(new CheckovSuppressionAspect());
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

// Log-stream APIs authorize on `...:log-group:<name>:*` (or `:log-stream:`).
// Every other logs: action authorizes on the log-group ARN. From April 26,
// 2027 a stream ARN no longer grants those actions (AWS Health planned
// lifecycle event; same rule as evolvesprouts #2175).
const LOG_STREAM_SCOPED_ACTIONS = new Set([
  "logs:PutLogEvents",
  "logs:GetLogEvents",
  "logs:CreateLogStream",
  "logs:DeleteLogStream",
]);

function flattenArn(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (value && typeof value === "object" && "Fn::Join" in value) {
    const [, parts] = (value as { "Fn::Join": [string, unknown[]] })["Fn::Join"];
    return parts.map((part) => (typeof part === "string" ? part : "<token>")).join("");
  }
  return JSON.stringify(value);
}

function isLogStreamArn(arn: string): boolean {
  return arn.endsWith(":*") || arn.includes(":log-stream:");
}

/** Error text when an Allow grants log-group actions only on stream ARNs. */
function logGroupActionOnStreamArnOnly(statement: Record<string, unknown>): string | undefined {
  if (statement.Effect !== "Allow") {
    return undefined;
  }
  const actions = ([] as unknown[]).concat(statement.Action ?? []);
  const groupActions = actions.filter(
    (action): action is string =>
      typeof action === "string" &&
      action.startsWith("logs:") &&
      !LOG_STREAM_SCOPED_ACTIONS.has(action),
  );
  if (groupActions.length === 0) {
    return undefined;
  }
  const arns = ([] as unknown[])
    .concat(statement.Resource ?? [])
    .map(flattenArn)
    .filter((arn) => arn.includes(":logs:"));
  if (arns.some(isLogStreamArn) && !arns.some((arn) => !isLogStreamArn(arn))) {
    return `${groupActions.join(", ")} only on log-stream ARNs (${arns.join(", ")})`;
  }
  return undefined;
}

function joinedPolicyDocument(value: unknown): string | undefined {
  if (typeof value === "string") {
    return value;
  }
  if (value && typeof value === "object" && "Fn::Join" in value) {
    const [, parts] = (value as { "Fn::Join": [string, unknown[]] })["Fn::Join"];
    // A GetAtt log-group ARN is not a string in the template. Substitute a
    // log-group ARN so the stream suffix (`:*`) still classifies the resource.
    return parts
      .map((part) =>
        typeof part === "string" ? part : "arn:aws:logs:region:account:log-group:token",
      )
      .join("");
  }
  return undefined;
}

function statementsFromDocument(value: unknown): Record<string, unknown>[] {
  if (value && typeof value === "object" && "Statement" in value) {
    const statements = (value as { Statement?: unknown }).Statement;
    return Array.isArray(statements) ? (statements as Record<string, unknown>[]) : [];
  }
  const text = joinedPolicyDocument(value);
  if (!text) {
    return [];
  }
  try {
    const parsed = JSON.parse(text) as { Statement?: unknown };
    return Array.isArray(parsed.Statement) ? (parsed.Statement as Record<string, unknown>[]) : [];
  } catch {
    return [];
  }
}

function logGroupArnViolations(template: Template): string[] {
  const violations: string[] = [];
  const policies = {
    ...template.findResources("AWS::IAM::Policy"),
    ...template.findResources("AWS::Logs::ResourcePolicy"),
  };
  for (const [logicalId, resource] of Object.entries(policies)) {
    const statements = statementsFromDocument(
      (resource as CfnResource).Properties?.PolicyDocument,
    );
    for (const statement of statements) {
      const detail = logGroupActionOnStreamArnOnly(statement);
      if (detail) {
        violations.push(`${logicalId} grants ${detail}; add the log-group ARN`);
      }
    }
  }
  return violations;
}

/** Production parameter values, keyed by CloudFormation parameter id. */
function productionParamValues(): Record<string, string> {
  const raw = JSON.parse(
    fs.readFileSync(path.join(__dirname, "../params/production.json"), "utf8")
  ) as Record<string, unknown>;
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value !== "string" || !key.startsWith("lxsoftware:")) continue;
    out[key.slice("lxsoftware:".length)] = value;
  }
  return out;
}

/**
 * Resolved length of one Lambda environment value.
 * Parameter refs use the production value when set, otherwise the template default.
 * A generated physical id (table, bucket, key) is budgeted at 64 bytes.
 * A resolved Secrets Manager ARN (DescribeSecret) is budgeted at 120 bytes.
 */
function cfnStringBytes(
  value: unknown,
  parameters: Record<string, { Default?: unknown }>,
  production: Record<string, string>
): number {
  if (typeof value === "string") return value.length;
  if (typeof value === "number" || typeof value === "boolean") return String(value).length;
  if (!value || typeof value !== "object" || Array.isArray(value)) return 64;
  const obj = value as Record<string, unknown>;
  if (typeof obj.Ref === "string") {
    if (obj.Ref.startsWith("AWS::")) return 16;
    if (Object.prototype.hasOwnProperty.call(production, obj.Ref)) return production[obj.Ref]!.length;
    if (Object.prototype.hasOwnProperty.call(parameters, obj.Ref)) {
      const def = parameters[obj.Ref]?.Default;
      return typeof def === "string" ? def.length : 0;
    }
    return 64;
  }
  const join = obj["Fn::Join"];
  if (Array.isArray(join) && Array.isArray(join[1])) {
    return (join[1] as unknown[]).reduce<number>(
      (total, part) => total + cfnStringBytes(part, parameters, production),
      0
    );
  }
  const branch = obj["Fn::If"];
  if (Array.isArray(branch)) {
    return Math.max(
      cfnStringBytes(branch[1], parameters, production),
      cfnStringBytes(branch[2], parameters, production)
    );
  }
  if (obj["Fn::GetAtt"]) return 120;
  return 64;
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
    "GET /v1/webhooks/meta",
    "POST /v1/webhooks/meta",
    "GET /v1/webhooks/meta/siutindei",
    "POST /v1/webhooks/meta/siutindei",
    // RFC 8058 one-click / browser unsubscribe; HMAC in the token, no JWT.
    // The /public copies stay because they are already in sent email.
    "GET /public/outreach/unsubscribe/{token}",
    "POST /public/outreach/unsubscribe/{token}",
    "GET /v1/public/outreach/unsubscribe/{token}",
    "POST /v1/public/outreach/unsubscribe/{token}",
    "POST /v1/public/newsletter/subscribe",
    "GET /public/newsletter/confirm/{token}",
    "GET /v1/public/newsletter/confirm/{token}",
    "GET /public/newsletter/unsubscribe/{token}",
    "POST /public/newsletter/unsubscribe/{token}",
    "GET /v1/public/newsletter/unsubscribe/{token}",
    "POST /v1/public/newsletter/unsubscribe/{token}",
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

  test("partner finance mirrors are GET-only; the board proxy accepts writes", () => {
    const routes = Object.values(resourcesOfType("AWS::ApiGatewayV2::Route"));
    const publicMirrors = routes.filter((r) => {
      const key = String(r.Properties?.RouteKey);
      return key.includes(" /v1/partner/");
    });
    expect(publicMirrors.length).toBeGreaterThan(0);
    const keys = publicMirrors.map((r) => String(r.Properties?.RouteKey));
    expect(keys).toEqual(
      expect.arrayContaining([
        "GET /v1/partner/lx-software/linkedin/posts",
        "POST /v1/partner/lx-software/linkedin/posts",
        "GET /v1/partner/lx-software/linkedin/posts/{id}",
        "PUT /v1/partner/lx-software/linkedin/posts/{id}",
        "DELETE /v1/partner/lx-software/linkedin/posts/{id}",
        "GET /v1/partner/siutindei/board",
        "GET /v1/partner/siutindei/board/{proxy+}",
        "PUT /v1/partner/siutindei/board/{proxy+}",
        "POST /v1/partner/siutindei/board/{proxy+}",
        "DELETE /v1/partner/siutindei/board/{proxy+}",
      ])
    );
    const boardProxyWrites = keys
      .filter(
        (key) =>
          key.includes("/v1/partner/siutindei/board/{proxy+}") && !key.startsWith("GET ")
      )
      .sort();
    expect(boardProxyWrites).toEqual([
      "DELETE /v1/partner/siutindei/board/{proxy+}",
      "POST /v1/partner/siutindei/board/{proxy+}",
      "PUT /v1/partner/siutindei/board/{proxy+}",
    ]);
    const legacyBoard = routes
      .filter((route) => String(route.Properties?.RouteKey).includes("/public/siu-tin-dei/board"))
      .map((route) => String(route.Properties?.RouteKey))
      .sort();
    expect(legacyBoard).toEqual([
      "DELETE /public/siu-tin-dei/board/{proxy+}",
      "GET /public/siu-tin-dei/board",
      "GET /public/siu-tin-dei/board/{proxy+}",
      "POST /public/siu-tin-dei/board/{proxy+}",
      "PUT /public/siu-tin-dei/board/{proxy+}",
    ]);
    for (const route of routes) {
      const key = String(route.Properties?.RouteKey);
      if (key.includes("/public/siu-tin-dei/board")) {
        expect(route.Properties?.AuthorizationType).toBe("CUSTOM");
      }
    }
    for (const route of publicMirrors) {
      const key = String(route.Properties?.RouteKey);
      expect(route.Properties?.AuthorizationType).toBe("CUSTOM");
      const linkedinWrite =
        key === "POST /v1/partner/lx-software/linkedin/posts" ||
        key === "PUT /v1/partner/lx-software/linkedin/posts/{id}" ||
        key === "DELETE /v1/partner/lx-software/linkedin/posts/{id}";
      if (!key.includes("/v1/partner/siutindei/board/{proxy+}") && !linkedinWrite) {
        expect(key).toMatch(/^GET /);
      }
    }
  });

  test("LinkedIn analytics connect and disconnect are JWT-protected", () => {
    const routes = Object.values(resourcesOfType("AWS::ApiGatewayV2::Route"));
    for (const key of [
      "POST /v1/admin/lx-software/linkedin/analytics/connect",
      "POST /v1/admin/lx-software/linkedin/analytics/disconnect",
    ]) {
      const route = routes.find((row) => row.Properties?.RouteKey === key);
      expect(route?.Properties?.AuthorizationType).toBe("JWT");
      expect(route?.Properties?.AuthorizerId).toBeDefined();
    }
  });

  test("LinkedIn picture and character routes are JWT-protected", () => {
    const routes = Object.values(resourcesOfType("AWS::ApiGatewayV2::Route"));
    const keys = [
      "GET /v1/admin/lx-software/linkedin/posts/{id}/image",
      "POST /v1/admin/lx-software/linkedin/posts/{id}/image",
      "DELETE /v1/admin/lx-software/linkedin/posts/{id}/image",
      "POST /v1/admin/lx-software/linkedin/posts/{id}/image/regenerate",
      "POST /v1/admin/lx-software/linkedin/posts/{id}/image/brief",
      "GET /v1/admin/lx-software/linkedin/character",
      "GET /v1/admin/lx-software/linkedin/character/photo",
      "POST /v1/admin/lx-software/linkedin/character/photo",
      "DELETE /v1/admin/lx-software/linkedin/character/photo",
      "GET /v1/admin/lx-software/linkedin/character/sheet",
      "POST /v1/admin/lx-software/linkedin/character/draw",
      "GET /v1/admin/lx-software/linkedin/character/candidates/{id}",
      "POST /v1/admin/lx-software/linkedin/character/choose",
    ];
    for (const key of keys) {
      const route = routes.find((row) => row.Properties?.RouteKey === key);
      expect(route?.Properties?.AuthorizationType).toBe("JWT");
    }
  });

  test("Resume routes are JWT-protected", () => {
    const routes = Object.values(resourcesOfType("AWS::ApiGatewayV2::Route"));
    const keys = [
      "GET /v1/admin/lx-software/resume/overview",
      "GET /v1/admin/lx-software/resume/settings",
      "PUT /v1/admin/lx-software/resume/settings",
      "GET /v1/admin/lx-software/resume/resumes",
      "POST /v1/admin/lx-software/resume/resumes",
      "GET /v1/admin/lx-software/resume/resumes/{id}",
      "PATCH /v1/admin/lx-software/resume/resumes/{id}",
      "DELETE /v1/admin/lx-software/resume/resumes/{id}",
      "GET /v1/admin/lx-software/resume/resumes/{id}/file",
      "GET /v1/admin/lx-software/resume/resumes/{id}/pdf",
      "PUT /v1/admin/lx-software/resume/template",
      "GET /v1/admin/lx-software/resume/postings",
      "POST /v1/admin/lx-software/resume/postings",
      "POST /v1/admin/lx-software/resume/tailor",
      "GET /v1/admin/lx-software/resume/applications",
      "POST /v1/admin/lx-software/resume/applications",
      "PATCH /v1/admin/lx-software/resume/applications/{id}",
      "DELETE /v1/admin/lx-software/resume/applications/{id}",
      "GET /v1/admin/lx-software/resume/jobs/{job_id}",
    ];
    for (const key of keys) {
      const route = routes.find((row) => row.Properties?.RouteKey === key);
      expect(route?.Properties?.AuthorizationType).toBe("JWT");
    }
  });

  test("AWS usage JSON and PDF routes are JWT-protected", () => {
    const routes = Object.values(resourcesOfType("AWS::ApiGatewayV2::Route"));
    const keys = routes.map((r) => r.Properties?.RouteKey as string);
    expect(keys).toEqual(expect.arrayContaining(["GET /v1/admin/aws/usage", "GET /v1/admin/aws/usage/pdf"]));
    for (const key of ["GET /v1/admin/aws/usage", "GET /v1/admin/aws/usage/pdf"]) {
      const route = routes.find((r) => r.Properties?.RouteKey === key);
      expect(route?.Properties?.AuthorizationType).toBe("JWT");
      expect(route?.Properties?.AuthorizerId).toBeDefined();
    }
  });
});

describe("API custom domain", () => {
  test("the regional domain and mapping exist only when both parameters are set", () => {
    const parameters = template.toJSON().Parameters as Record<string, { Default?: string }>;
    expect(parameters.ApiCustomDomainName.Default).toBe(API_CUSTOM_DOMAIN_DISABLED);
    expect(parameters.ApiCustomDomainCertificateArn.Default).toBe(API_CUSTOM_CERTIFICATE_DISABLED);

    const domains = resourcesOfType("AWS::ApiGatewayV2::DomainName");
    expect(Object.keys(domains)).toHaveLength(1);
    const domain = Object.values(domains)[0];
    expect(domain.Condition).toBe("UseApiCustomDomain");
    const config = domain.Properties?.DomainNameConfigurations?.[0];
    expect(config).toMatchObject({
      EndpointType: "REGIONAL",
      SecurityPolicy: "TLS_1_2",
      CertificateArn: { Ref: "ApiCustomDomainCertificateArn" },
    });
    expect(domain.Properties?.DomainName).toEqual({ Ref: "ApiCustomDomainName" });

    const mappings = resourcesOfType("AWS::ApiGatewayV2::ApiMapping");
    expect(Object.keys(mappings)).toHaveLength(1);
    const mapping = Object.values(mappings)[0];
    expect(mapping.Condition).toBe("UseApiCustomDomain");
    expect(mapping.Properties?.Stage).toBe("$default");
    const stages = resourcesOfType("AWS::ApiGatewayV2::Stage");
    const stageId = Object.keys(stages)[0];
    const depends = mapping.DependsOn;
    expect(Array.isArray(depends) ? depends : [depends]).toContain(stageId);

    const outputs = template.toJSON().Outputs as Record<string, { Condition?: string }>;
    expect(outputs.ApiCustomDomainTarget.Condition).toBe("UseApiCustomDomain");
    expect(outputs.ApiCustomDomainUrl.Condition).toBe("UseApiCustomDomain");

    const conditions = template.toJSON().Conditions as Record<string, unknown>;
    const serialized = JSON.stringify(conditions.UseApiCustomDomain);
    expect(serialized).toContain(API_CUSTOM_DOMAIN_DISABLED);
    expect(serialized).toContain(API_CUSTOM_CERTIFICATE_DISABLED);
    expect(serialized).toContain('""');

    const api = Object.values(resourcesOfType("AWS::ApiGatewayV2::Api"))[0];
    expect(api.Properties?.DisableExecuteApiEndpoint).toBeUndefined();
    const withBaseUrl = Object.values(resourcesOfType("AWS::Lambda::Function")).filter(
      (fn) => fn.Properties?.Environment?.Variables?.PUBLIC_API_BASE_URL !== undefined,
    );
    expect(withBaseUrl).toHaveLength(1);
    const baseUrl = JSON.stringify(
      withBaseUrl[0].Properties?.Environment?.Variables?.PUBLIC_API_BASE_URL,
    );
    expect(baseUrl).toContain("UseApiCustomDomain");
    expect(baseUrl).toContain("ApiCustomDomainName");
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
        "POST /v1/webhooks/meta": {
          ThrottlingRateLimit: 10,
          ThrottlingBurstLimit: 20,
        },
        "GET /v1/webhooks/meta": {
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
        "POST /v1/webhooks/meta/siutindei": {
          ThrottlingRateLimit: 10,
          ThrottlingBurstLimit: 20,
        },
        "GET /v1/webhooks/meta/siutindei": {
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

  test("public API-key routes are throttled tighter than the stage default", () => {
    template.hasResourceProperties("AWS::ApiGatewayV2::Stage", {
      StageName: "$default",
      RouteSettings: Match.objectLike({
        "GET /v1/partner/finance": {
          ThrottlingRateLimit: 2,
          ThrottlingBurstLimit: 10,
        },
        "GET /v1/partner/lx-software/linkedin/posts": {
          ThrottlingRateLimit: 2,
          ThrottlingBurstLimit: 10,
        },
        "POST /v1/partner/lx-software/linkedin/posts": {
          ThrottlingRateLimit: 1,
          ThrottlingBurstLimit: 5,
        },
        "GET /v1/partner/lx-software/linkedin/posts/{id}": {
          ThrottlingRateLimit: 2,
          ThrottlingBurstLimit: 10,
        },
        "PUT /v1/partner/lx-software/linkedin/posts/{id}": {
          ThrottlingRateLimit: 1,
          ThrottlingBurstLimit: 5,
        },
        "DELETE /v1/partner/lx-software/linkedin/posts/{id}": {
          ThrottlingRateLimit: 1,
          ThrottlingBurstLimit: 5,
        },
        "GET /v1/partner/siutindei/board/{proxy+}": {
          ThrottlingRateLimit: 2,
          ThrottlingBurstLimit: 10,
        },
        "POST /v1/partner/siutindei/board/{proxy+}": {
          ThrottlingRateLimit: 1,
          ThrottlingBurstLimit: 5,
        },
        "PUT /v1/partner/siutindei/board/{proxy+}": {
          ThrottlingRateLimit: 1,
          ThrottlingBurstLimit: 5,
        },
        "DELETE /v1/partner/siutindei/board/{proxy+}": {
          ThrottlingRateLimit: 1,
          ThrottlingBurstLimit: 5,
        },
        "GET /public/siu-tin-dei/board": {
          ThrottlingRateLimit: 2,
          ThrottlingBurstLimit: 10,
        },
        "GET /public/siu-tin-dei/board/{proxy+}": {
          ThrottlingRateLimit: 2,
          ThrottlingBurstLimit: 10,
        },
        "POST /public/siu-tin-dei/board/{proxy+}": {
          ThrottlingRateLimit: 1,
          ThrottlingBurstLimit: 5,
        },
        "PUT /public/siu-tin-dei/board/{proxy+}": {
          ThrottlingRateLimit: 1,
          ThrottlingBurstLimit: 5,
        },
        "DELETE /public/siu-tin-dei/board/{proxy+}": {
          ThrottlingRateLimit: 1,
          ThrottlingBurstLimit: 5,
        },
      }),
    });
  });

  test("public API-key authorizer does not cache a source-IP result", () => {
    template.hasResourceProperties("AWS::ApiGatewayV2::Authorizer", {
      AuthorizerType: "REQUEST",
      EnableSimpleResponses: true,
      AuthorizerResultTtlInSeconds: 0,
      IdentitySource: ["$context.identity.sourceIp"],
    });
    const sources = Object.values(resourcesOfType("AWS::ApiGatewayV2::Authorizer"))
      .filter((item) => item.Properties?.AuthorizerType === "REQUEST")
      .flatMap((item) => (item.Properties?.IdentitySource ?? []) as string[]);
    const headers = sources.filter((item) => item.includes(".header."));
    const both =
      headers.includes("$request.header.Authorization") &&
      headers.includes("$request.header.x-api-key");
    expect(headers.length === 0 || both).toBe(true);
    expect(sources).toContain("$context.identity.sourceIp");
  });

  test("public API-key metric filters use term patterns (Lambda log lines are not JSON)", () => {
    const filters = Object.values(resourcesOfType("AWS::Logs::MetricFilter"));
    const patterns = filters
      .filter((f) =>
        ["ApiKeyDenied", "BoardFullAccess", "PublicApiWrite"].includes(
          f.Properties?.MetricTransformations?.[0]?.MetricName
        )
      )
      .map((f) => f.Properties?.FilterPattern as string);
    expect(patterns).toHaveLength(3);
    for (const pattern of patterns) {
      expect(pattern.trim().startsWith("{")).toBe(false);
    }
  });

  test("the default stage waits for Meta webhook routes before RouteSettings", () => {
    const [, stage] = Object.entries(resourcesOfType("AWS::ApiGatewayV2::Stage")).find(
      ([, r]) => r.Properties?.StageName === "$default"
    )!;
    const webhookRouteIds = Object.entries(resourcesOfType("AWS::ApiGatewayV2::Route"))
      .filter(([, r]) => String(r.Properties?.RouteKey).includes("/webhooks/meta"))
      .map(([id]) => id);
    expect(webhookRouteIds).toHaveLength(8);
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

  test("no Lambda resource-policy statement is granted to scheduler.amazonaws.com or events.amazonaws.com", () => {
    const permissions = Object.values(resourcesOfType("AWS::Lambda::Permission"));
    const schedulerGrants = permissions.filter(
      (p) => p.Properties?.Principal === "scheduler.amazonaws.com"
    );
    expect(schedulerGrants).toEqual([]);
    const eventRuleGrants = permissions.filter(
      (p) => p.Properties?.Principal === "events.amazonaws.com"
    );
    expect(eventRuleGrants).toEqual([]);
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
      "lxsoftware-admin-siutindei-board-catalog-discovery": "board_catalog_discovery",
      "lxsoftware-admin-siutindei-board-intel-weekly": "board_intel_weekly",
      "lxsoftware-admin-siutindei-board-targets": "board_targets",
      "lxsoftware-admin-siutindei-board-content-plan": "board_content_plan",
      "lxsoftware-admin-siutindei-board-content-readout": "board_content_readout",
      "lxsoftware-admin-siutindei-data-api-ensure": "siutindei_data_api_ensure",
    };
    const accountSchedules: Record<string, string> = {
      "lxsoftware-admin-openrouter-usage-pull": "openrouter_usage_pull",
      "lxsoftware-admin-evolvesprouts-data-api-ensure": "data_api_ensure",
      "lxsoftware-admin-evolvesprouts-finance-mirror": "evolvesprouts_finance_mirror",
      "lxsoftware-admin-bank-sync": "bank_sync",
      "lxsoftware-admin-linkedin-plan": "linkedin_weekly_plan",
      "lxsoftware-admin-linkedin-publish": "linkedin_publish_due",
    };
    const schedules = Object.values(resourcesOfType("AWS::Scheduler::Schedule"));
    const byName = Object.fromEntries(
      schedules
        .filter((s) => typeof s.Properties?.Name === "string")
        .map((s) => [s.Properties?.Name as string, s])
    );
    expect(Object.keys(byName).sort()).toEqual(
      [...Object.keys(expected), ...Object.keys(accountSchedules)].sort()
    );
    for (const [name, internal] of Object.entries(expected)) {
      const input = JSON.stringify(byName[name].Properties?.Target?.Input ?? "");
      expect(input).toContain(internal);
      expect(input).toContain("siuTinDei");
    }
    for (const [name, internal] of Object.entries(accountSchedules)) {
      const input = JSON.stringify(byName[name].Properties?.Target?.Input ?? "");
      expect(input).toContain(internal);
      expect(input).not.toContain("siuTinDei");
    }
    expect(byName["lxsoftware-admin-linkedin-plan"].Condition).toBe("LxSoftwareLinkedinSchedules");
    expect(byName["lxsoftware-admin-linkedin-publish"].Condition).toBe("LxSoftwareLinkedinSchedules");
    expect(byName["lxsoftware-admin-bank-sync"].Condition).toBeUndefined();
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
    ["AdminEvolvesproutsDataApiPolicy", "HasEvolvesproutsDataApi"],
    ["SiutindeiBoardMailSendPolicy", "HasSiutindeiBoardMailSending"],
    ["SiutindeiBoardImporterAuthPolicy", "HasSiutindeiUserPool"],
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

describe("Board message media retention", () => {
  test("photos expire after 90 days and the old version goes a day later", () => {
    const rules = Object.values(template.toJSON().Resources as Record<string, CfnResource>)
      .filter((resource) => resource.Type === "AWS::S3::Bucket")
      .flatMap((bucket) => bucket.Properties?.LifecycleConfiguration?.Rules ?? [])
      .filter((rule: { Id?: string }) => rule.Id === "ExpireBoardMetaMedia");
    expect(rules).toEqual([
      {
        Id: "ExpireBoardMetaMedia",
        Status: "Enabled",
        Prefix: "board/meta-media/",
        ExpirationInDays: 90,
        NoncurrentVersionExpiration: { NoncurrentDays: 1 },
      },
    ]);
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
    "AdminBootstrapEmail",
    "AdminBootstrapTempPassword",
  ];

  function secretsNamed(names: string[]): CfnResource[] {
    return Object.values(resourcesOfType("AWS::SecretsManager::Secret")).filter((r) =>
      names.includes(r.Properties?.Name as string)
    );
  }

  test("omits unused LX Software placeholder secrets and imports the Siu Tin Dei set", () => {
    // Those seven secrets were RETAIN placeholders AdminApiFn never read.
    // Dropping them from the template orphans the secret values in the account.
    expect(secretsNamed(reservedNames)).toEqual([]);
    expect(secretsNamed(siutindeiNames)).toEqual([]);
    const importer = secretsNamed([
      "lxsoftware-admin-siutindei-board-importer-credentials",
    ]);
    expect(importer).toHaveLength(1);
    expect(importer[0].DeletionPolicy).toBe("Retain");
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

  test("LxSoftwareLinkedin switches default off", () => {
    const parameters = template.toJSON().Parameters as Record<
      string,
      { Default?: string; AllowedValues?: string[] }
    >;
    expect(parameters.LxSoftwareLinkedinEnabled?.Default).toBe("false");
    expect(parameters.LxSoftwareLinkedinEnabled?.AllowedValues).toEqual(["true", "false"]);
    expect(parameters.LxSoftwareLinkedinPublishEnabled?.Default).toBe("false");
    expect(parameters.LxSoftwareLinkedinPublishEnabled?.AllowedValues).toEqual(["true", "false"]);
    expect(parameters.LxSoftwareResumeEnabled?.Default).toBe("false");
    expect(parameters.LxSoftwareResumeEnabled?.AllowedValues).toEqual(["true", "false"]);
    const linkedinSecret = Object.values(resourcesOfType("AWS::SecretsManager::Secret")).find(
      (resource) => resource.Properties?.Name === "lxsoftware-admin-linkedin-app"
    );
    expect(linkedinSecret?.DeletionPolicy).toBe("Retain");
    const adminFn = Object.entries(resourcesOfType("AWS::Lambda::Function")).find(([id]) =>
      id.startsWith("AdminApiFn")
    );
    expect(adminFn?.[1].Properties?.Environment?.Variables?.LINKEDIN_APP_SECRET_ID).toBe(
      "lxsoftware-admin-linkedin-app"
    );
    expect(adminFn?.[1].Properties?.Environment?.Variables?.RESUME_ENABLED).toEqual({
      Ref: "LxSoftwareResumeEnabled",
    });
  });

  test("SiutindeiBoardCatalogImportEnabled defaults off", () => {
    const parameters = template.toJSON().Parameters as Record<
      string,
      { Default?: string; AllowedValues?: string[] }
    >;
    expect(parameters.SiutindeiBoardCatalogImportEnabled?.Default).toBe("false");
    expect(parameters.SiutindeiBoardCatalogImportEnabled?.AllowedValues).toEqual(["true", "false"]);
    expect(parameters.CatalogImportEnabled).toBeUndefined();
  });

  test("PublicApiWritesEnabled is unprefixed and defaults off", () => {
    const parameters = template.toJSON().Parameters as Record<
      string,
      { Default?: string; AllowedValues?: string[] }
    >;
    expect(parameters.PublicApiWritesEnabled?.Default).toBe("false");
    expect(parameters.PublicApiWritesEnabled?.AllowedValues).toEqual(["true", "false"]);
    expect(parameters.SiutindeiBoardPublicApiWritesEnabled).toBeUndefined();
  });

  test("AdminApiFn can PutItem on the audit log table", () => {
    const audit = Object.entries(resourcesOfType("AWS::DynamoDB::Table")).find(
      ([, resource]) => resource.Properties?.TableName === "lxsoftware-admin-audit-log",
    );
    expect(audit).toBeDefined();
    const [auditId] = audit!;
    const writes = Object.entries(resourcesOfType("AWS::IAM::Policy"))
      .filter(([id]) => id.startsWith("AdminApiFn"))
      .flatMap(([, policy]) => policyStatements(policy))
      .filter(
        (statement) =>
          asArray<string>(statement.Action).includes("dynamodb:PutItem") &&
          JSON.stringify(statement.Resource).includes(auditId),
      );
    expect(writes.length).toBeGreaterThan(0);
  });

  test("PublicApiWritesEnabled is on AdminApiFn only, not the authorizer", () => {
    const fns = Object.entries(resourcesOfType("AWS::Lambda::Function"));
    const authorizer = fns.find(([id]) =>
      id.startsWith("PublicApiKeyAuthorizerFn")
    );
    expect(authorizer).toBeDefined();
    expect(
      authorizer?.[1].Properties?.Environment?.Variables
        ?.PUBLIC_API_WRITES_ENABLED
    ).toBeUndefined();
    const withWrites = fns.filter(
      ([, r]) =>
        r.Properties?.Environment?.Variables?.PUBLIC_API_WRITES_ENABLED !==
        undefined
    );
    expect(withWrites.length).toBeGreaterThanOrEqual(1);
    expect(withWrites.every(([id]) => id.startsWith("AdminApiFn"))).toBe(true);
  });

  test("production.json keys name parameters on the stack that defines them", () => {
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
    expect(lxsoftwareKeys).toContain("lxsoftware:PublicApiWritesEnabled");
    expect(file["lxsoftware:PublicApiWritesEnabled"]).toBe("true");
    expect(file["lxsoftware:LxSoftwareLinkedinEnabled"]).toBe("true");
    expect(file["lxsoftware:LxSoftwareLinkedinPublishEnabled"]).toBe("true");
    expect(file["lxsoftware:LxSoftwareResumeEnabled"]).toBe("true");
    expect(file["lxsoftware:SiutindeiAdminApiBaseUrl"]).toBe(
      "https://api.siutindei.com",
    );
    expect(file["lxsoftware:ApiCustomDomainName"]).toBe("api.lx-software.com");
    expect(file["lxsoftware:ApiCustomDomainCertificateArn"]).toBe(
      "<FROM_GITHUB_SECRET: CDK_PARAM_API_CUSTOM_DOMAIN_CERTIFICATE_ARN>",
    );

    const env = { account: "123456789012", region: "ap-southeast-1" };
    const publicApp = new cdk.App({
      context: { "aws:cdk:bundling-stacks": [] },
    });
    const publicParameters = Template.fromStack(
      new PublicWebsiteStack(publicApp, "lxsoftware-public-www", { env }),
    ).toJSON().Parameters as Record<string, unknown>;
    const adminWebApp = new cdk.App({
      context: { "aws:cdk:bundling-stacks": [] },
    });
    const adminWebParameters = Template.fromStack(
      new LxsoftwareAdminWebStack(adminWebApp, "lxsoftware-admin-web", {
        env,
        cspApiConnectOrigin: "https://example.execute-api.ap-southeast-1.amazonaws.com",
        cspAssetsConnectOrigins: "https://bucket.s3.amazonaws.com",
      }),
    ).toJSON().Parameters as Record<string, unknown>;

    for (const key of Object.keys(file)) {
      if (key.startsWith("lxsoftware-admin-web:")) {
        expect(adminWebParameters[key.slice("lxsoftware-admin-web:".length)]).toBeDefined();
      } else if (key.startsWith("lxsoftware-public-www:")) {
        expect(publicParameters[key.slice("lxsoftware-public-www:".length)]).toBeDefined();
      } else if (key.startsWith("lxsoftware:")) {
        expect(parameters[key.slice("lxsoftware:".length)]).toBeDefined();
      } else if (!key.includes(":")) {
        expect(publicParameters[key]).toBeDefined();
      } else {
        throw new Error(`unknown parameter key prefix: ${key}`);
      }
    }
    expect(() => {
      const unknown = "other-stack:NotAParameter";
      if (unknown.includes(":") && !unknown.startsWith("lxsoftware:") && !unknown.startsWith("lxsoftware-admin-web:") && !unknown.startsWith("lxsoftware-public-www:")) {
        throw new Error(`unknown parameter key prefix: ${unknown}`);
      }
    }).toThrow(/unknown parameter key prefix/);
  });

  test("AdminApiFn environment keys are unique", () => {
    const adminFn = Object.entries(resourcesOfType("AWS::Lambda::Function")).find(([id]) =>
      id.startsWith("AdminApiFn"),
    );
    const env = (adminFn?.[1].Properties?.Environment?.Variables ?? {}) as Record<string, unknown>;
    const keys = Object.keys(env);
    expect(keys.length).toBeGreaterThan(40);
    expect(new Set(keys).size).toBe(keys.length);
    for (const name of [
      "BOARD_STAFF_ENABLED",
      "BOARD_TOOLS_ENABLED",
      "BOARD_MAIL_SENDING_ENABLED",
      "OUTREACH_SENDING_DOMAIN",
      "OUTREACH_FROM_LOCAL_PART",
    ]) {
      expect(keys.filter((key) => key === name)).toHaveLength(1);
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

  test("OpenRouterModel defaults to Mistral Large 4", () => {
    expect(template.toJSON().Parameters.OpenRouterModel.Default).toBe(
      "mistralai/mistral-large-4-0",
    );
  });

  test("Secrets Manager reference parameters are NoEcho", () => {
    const params = template.toJSON().Parameters;
    for (const name of [
      "OpenRouterApiKeySecretArn",
      "SiutindeiDbSecretArn",
      "SiutindeiDbSecretName",
      "EvolvesproutsDbSecretArn",
      "EvolvesproutsDbSecretName",
    ]) {
      expect(params[name].NoEcho).toBe(true);
    }
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

describe("Admin user pool sign-in gate", () => {
  test("Pre Sign-up and Pre Token Generation both run the allow-list Lambda", () => {
    const pools = Object.values(resourcesOfType("AWS::Cognito::UserPool"));
    expect(pools).toHaveLength(1);
    const lambdaConfig = pools[0].Properties?.LambdaConfig ?? {};
    const preSignUp = lambdaConfig.PreSignUp;
    const preToken = lambdaConfig.PreTokenGeneration;
    expect(preSignUp).toBeTruthy();
    expect(preToken).toBeTruthy();
    expect(preSignUp).toEqual(preToken);
    const fnLogicalId = preToken?.["Fn::GetAtt"]?.[0];
    expect(fnLogicalId).toMatch(/PreTokenGenerationFn/);
    expect(resources[fnLogicalId]?.Properties?.Environment?.Variables).toMatchObject({
      ADMIN_EMAIL_ALLOWLIST: { Ref: "AdminFederatedEmailAllowlist" },
    });
  });

  test("the federated email allow-list parameter is NoEcho", () => {
    expect(template.toJSON().Parameters.AdminFederatedEmailAllowlist.NoEcho).toBe(true);
  });

  test("Cognito may invoke the gate for both triggers", () => {
    const permissions = Object.values(resourcesOfType("AWS::Lambda::Permission")).filter(
      (p) =>
        p.Properties?.Principal === "cognito-idp.amazonaws.com" &&
        JSON.stringify(p.Properties?.FunctionName).includes("PreTokenGenerationFn"),
    );
    expect(permissions.length).toBeGreaterThanOrEqual(1);
    for (const permission of permissions) {
      expect(JSON.stringify(permission.Properties?.SourceArn)).toMatch(/UserPool/);
    }
  });

  test("the pool has no self sign-up and the SPA client has no secret", () => {
    const pool = Object.values(resourcesOfType("AWS::Cognito::UserPool"))[0];
    expect(pool.Properties?.AdminCreateUserConfig?.AllowAdminCreateUserOnly).toBe(true);
    const clients = Object.values(resourcesOfType("AWS::Cognito::UserPoolClient"));
    expect(clients).toHaveLength(1);
    expect(clients[0].Properties?.GenerateSecret).toBe(false);
  });

  test("the SPA client signs in with Google and a refresh token only", () => {
    const providers = Object.values(
      resourcesOfType("AWS::Cognito::UserPoolIdentityProvider"),
    );
    expect(providers).toHaveLength(1);
    expect(providers[0].Properties?.ProviderName).toBe("Google");
    expect(providers[0].Properties?.ProviderType).toBe("Google");
    const clients = Object.values(resourcesOfType("AWS::Cognito::UserPoolClient"));
    expect(clients[0].Properties?.SupportedIdentityProviders).toEqual([
      { Ref: expect.stringMatching(/GoogleProvider/) },
    ]);
    expect(clients[0].Properties?.ExplicitAuthFlows).toEqual(["ALLOW_REFRESH_TOKEN_AUTH"]);
    // These logical ids are already deployed. Renaming the construct replaces
    // the live user pool or app client and changes the client id the SPA reads.
    expect(Object.keys(resourcesOfType("AWS::Cognito::UserPool"))).toEqual([
      "AuthUserPool8115E87F",
    ]);
    expect(Object.keys(resourcesOfType("AWS::Cognito::UserPoolClient"))).toEqual([
      "AuthUserPoolUserPoolClientBB863FCC",
    ]);
    const templateJson = JSON.stringify(template.toJSON());
    expect(templateJson).not.toContain("adminCreateUser");
    expect(templateJson).not.toContain("adminSetUserPassword");
    expect(templateJson).not.toContain("adminAddUserToGroup");
    expect(templateJson).not.toContain("adminGetUser");
  });

  test("the custom Hosted UI domain stays off for an empty value or the disabled default", () => {
    const certificatePattern =
      /^arn:[\w+=/,.@-]+:[\w+=/,.@-]+:([\w+=/,.@-]*)?:[0-9]+:[\w+=/,.@-]+(:[\w+=/,.@-]+)?(:[\w+=/,.@-]+)?$/;
    expect(COGNITO_CUSTOM_DOMAIN_DISABLED.length).toBeGreaterThanOrEqual(1);
    expect(COGNITO_CUSTOM_CERTIFICATE_DISABLED).toMatch(certificatePattern);
    expect(COGNITO_CUSTOM_CERTIFICATE_DISABLED.length).toBeGreaterThanOrEqual(20);

    const parameters = template.toJSON().Parameters;
    expect(parameters.CognitoCustomDomainName.Default).toBe(COGNITO_CUSTOM_DOMAIN_DISABLED);
    expect(parameters.CognitoCustomDomainCertificateArn.Default).toBe(
      COGNITO_CUSTOM_CERTIFICATE_DISABLED
    );
    const domains = Object.entries(resourcesOfType("AWS::Cognito::UserPoolDomain"));
    expect(domains).toHaveLength(2);
    const custom = domains.find(([, resource]) => resource.Properties?.CustomDomainConfig);
    const prefix = domains.find(([, resource]) => !resource.Properties?.CustomDomainConfig);
    expect(custom?.[1].Condition).toMatch(/UseCustomAuthDomain/);
    expect(prefix?.[1].Condition).toMatch(/UseCognitoPrefixAuthDomain/);
    expect(custom?.[1].Properties?.Domain).toEqual({ Ref: "CognitoCustomDomainName" });
    expect(custom?.[1].Properties?.CustomDomainConfig?.CertificateArn).toEqual({
      Ref: "CognitoCustomDomainCertificateArn",
    });

    const conditions = template.toJSON().Conditions as Record<string, unknown>;
    const customCondition = JSON.stringify(
      conditions[custom?.[1].Condition as string]
    );
    const prefixCondition = JSON.stringify(
      conditions[prefix?.[1].Condition as string]
    );
    for (const serialized of [customCondition, prefixCondition]) {
      expect(serialized).toContain(COGNITO_CUSTOM_DOMAIN_DISABLED);
      expect(serialized).toContain(COGNITO_CUSTOM_CERTIFICATE_DISABLED);
      expect(serialized).toContain('""');
    }
  });

  test("CloudFormation Validate reports no W1030 for these defaults, and still reports one elsewhere", () => {
    const outdir = fs.mkdtempSync(path.join(os.tmpdir(), "cdk-w1030-"));
    const app = new cdk.App({
      outdir,
      context: { "aws:cdk:bundling-stacks": [] },
    });
    const stack = new LxsoftwareStack(app, "lxsoftware", {
      env: { account: "123456789012", region: "ap-southeast-1" },
    });
    const acknowledged = [stack, ...stack.node.findAll()].flatMap((construct) =>
      construct.node.metadata.filter(
        (entry) =>
          entry.type === cdk.Validations.ACKNOWLEDGED_RULES_METADATA_KEY &&
          JSON.stringify(entry.data).includes("W1030")
      )
    );
    expect(acknowledged).toEqual([]);
    // jest.config.js turns validation off so the suite stays quiet.
    // This test turns it back on for the same check `cdk synth` runs.
    const previousValidation = process.env.CDK_VALIDATION;
    process.env.CDK_VALIDATION = "true";
    const probe = new cdk.Stack(app, "probe", {
      env: { account: "123456789012", region: "ap-southeast-1" },
    });
    const pool = new cognito.UserPool(probe, "Pool");
    const emptyCertificate = new cdk.CfnParameter(probe, "EmptyCertificateArn", {
      type: "String",
      default: "",
    });
    new cognito.CfnUserPoolDomain(probe, "UnguardedDomain", {
      userPoolId: pool.userPoolId,
      domain: "probe.example.com",
      customDomainConfig: { certificateArn: emptyCertificate.valueAsString },
    });

    let violations: ReturnType<typeof cloudFormationViolations>;
    const reportError = console.error;
    console.error = () => undefined;
    try {
      violations = cloudFormationViolations(app);
    } finally {
      console.error = reportError;
      if (previousValidation === undefined) {
        delete process.env.CDK_VALIDATION;
      } else {
        process.env.CDK_VALIDATION = previousValidation;
      }
      cdk.CloudFormationValidatePlugin._disposeSingleton();
    }
    const lxsoftware = violations.filter((violation) =>
      violation.constructPath.startsWith("lxsoftware")
    );
    const probeViolations = violations.filter((violation) =>
      violation.constructPath.startsWith("probe")
    );
    expect(lxsoftware).toEqual([]);
    expect(
      probeViolations.some(
        (violation) =>
          violation.ruleName === "W1030" &&
          violation.description.includes("EmptyCertificateArn")
      )
    ).toBe(true);
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

describe("CloudWatch Logs IAM resource ARNs", () => {
  const logGroupArn =
    "arn:aws:logs:ap-southeast-1:123456789012:log-group:lxsoftware-admin-api-access-logs";

  test("flags log-group actions granted only on a log-stream ARN", () => {
    const detail = logGroupActionOnStreamArnOnly({
      Effect: "Allow",
      Action: ["logs:AssociateKmsKey", "logs:PutRetentionPolicy"],
      Resource: `${logGroupArn}:*`,
    });
    expect(detail).toContain("logs:AssociateKmsKey");
    expect(detail).toContain("logs:PutRetentionPolicy");
    expect(detail).toContain(`${logGroupArn}:*`);
  });

  test("passes when the log-group ARN is granted beside the stream ARN", () => {
    expect(
      logGroupActionOnStreamArnOnly({
        Effect: "Allow",
        Action: ["logs:AssociateKmsKey", "logs:PutRetentionPolicy"],
        Resource: [logGroupArn, `${logGroupArn}:*`],
      }),
    ).toBeUndefined();
  });

  test("leaves stream actions on the stream ARN", () => {
    expect(
      logGroupActionOnStreamArnOnly({
        Effect: "Allow",
        Action: ["logs:CreateLogStream", "logs:PutLogEvents"],
        Resource: `${logGroupArn}:*`,
      }),
    ).toBeUndefined();
  });

  test("does not flag a star resource", () => {
    expect(
      logGroupActionOnStreamArnOnly({
        Effect: "Allow",
        Action: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        Resource: "*",
      }),
    ).toBeUndefined();
  });

  test("no stack grants a log-group action only on a stream ARN", () => {
    const accessLogs = template.findResources("AWS::Logs::ResourcePolicy");
    const accessStatements = Object.values(accessLogs).flatMap((resource) =>
      statementsFromDocument((resource as CfnResource).Properties?.PolicyDocument),
    );
    expect(JSON.stringify(accessStatements)).toContain("logs:CreateLogStream");
    expect(logGroupArnViolations(template)).toEqual([]);

    const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } });
    new PublicWebsiteStack(app, "lxsoftware-public-www", {
      env: { account: "123456789012", region: "us-east-1" },
    });
    new LxsoftwareAdminWebStack(app, "lxsoftware-admin-web", {
      env: { account: "123456789012", region: "ap-southeast-1" },
      cspApiConnectOrigin: "https://example.execute-api.ap-southeast-1.amazonaws.com",
      cspAssetsConnectOrigins: "https://bucket.s3.amazonaws.com",
    });
    for (const child of app.node.children) {
      if (cdk.Stack.isStack(child)) {
        expect(logGroupArnViolations(Template.fromStack(child))).toEqual([]);
      }
    }
  });
});

describe("AdminApiFn recursive loop detection", () => {
  test("allows intentional self-invoke; other app Lambdas stay on Terminate", () => {
    const fns = resourcesOfType("AWS::Lambda::Function");
    const admin = Object.entries(fns).find(([id]) => id.startsWith("AdminApiFn"));
    expect(admin?.[1].Properties?.RecursiveLoop).toBe("Allow");
    const inbound = Object.entries(fns).find(([id]) =>
      id.startsWith("InboundStatementMailFn")
    );
    expect(inbound?.[1].Properties?.RecursiveLoop).toBeUndefined();
    const authorizer = Object.entries(fns).find(([id]) =>
      id.startsWith("PublicApiKeyAuthorizerFn")
    );
    expect(authorizer?.[1].Properties?.RecursiveLoop).toBeUndefined();
  });

  test("invocations alarm is named for the siutindei board alarm filter", () => {
    const alarms = Object.values(resourcesOfType("AWS::CloudWatch::Alarm"));
    const alarm = alarms.find(
      (r) => r.Properties?.AlarmName === "lxsoftware-admin-siutindei-admin-api-invocations"
    );
    expect(alarm).toBeDefined();
    expect(alarm?.Properties?.Threshold).toBe(250);
    expect(alarm?.Properties?.Namespace ?? alarm?.Properties?.Metrics).toBeDefined();
    const serialized = JSON.stringify(alarm?.Properties ?? {});
    expect(serialized).toContain("AWS/Lambda");
    expect(serialized).toContain("Invocations");
    expect(String(alarm?.Properties?.AlarmName)).toContain("siutindei");
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
  test("outreach identity publishes DKIM CNAME outputs", () => {
    const outputs = template.toJSON().Outputs as Record<string, { Description?: string }>;
    for (const n of [1, 2, 3]) {
      const key = `SiutindeiOutreachDkimCname${n}`;
      expect(outputs[key]).toBeDefined();
      expect(String(outputs[key]?.Description ?? "")).toContain("DKIM CNAME");
    }
  });

  test("board mail sending identity uses a custom MAIL FROM subdomain", () => {
    const identities = Object.entries(resourcesOfType("AWS::SES::EmailIdentity")).map(
      ([id, resource]) => ({ id, ...(resource as { Properties?: Record<string, unknown>; Condition?: string }) })
    );
    const boardMail = identities.find((row) => row.id.startsWith("SiutindeiBoardMailSendingIdentity"));
    expect(boardMail).toBeDefined();
    const mailFrom = (boardMail?.Properties?.MailFromAttributes || {}) as {
      MailFromDomain?: unknown;
      BehaviorOnMxFailure?: string;
    };
    expect(JSON.stringify(mailFrom.MailFromDomain)).toContain("SiutindeiBoardMailDomain");
    expect(JSON.stringify(mailFrom.MailFromDomain)).toContain('"mail"');
    expect(mailFrom.BehaviorOnMxFailure).toBe("USE_DEFAULT_VALUE");
  });

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

  test("CORS allows every method on a JWT route and exposes the request id", () => {
    const api = Object.values(resourcesOfType("AWS::ApiGatewayV2::Api"))[0];
    const cors = api.Properties?.CorsConfiguration as {
      AllowMethods?: string[];
      ExposeHeaders?: string[];
    };
    const allowed = cors.AllowMethods ?? [];
    expect(allowed).toContain("PATCH");
    expect(cors.ExposeHeaders).toContain("x-request-id");
    for (const route of Object.values(resourcesOfType("AWS::ApiGatewayV2::Route"))) {
      if (route.Properties?.AuthorizationType !== "JWT") continue;
      const method = String(route.Properties?.RouteKey).split(" ")[0];
      expect(allowed).toContain(method);
    }
  });

  test("CORS origins include the PublicSiteOrigins parameter", () => {
    const serialized = JSON.stringify(template.toJSON());
    expect(serialized).toContain("PublicSiteOrigins");
    expect(serialized).toContain("lx-software.com");
    const api = Object.values(resourcesOfType("AWS::ApiGatewayV2::Api"))[0];
    const allowOrigins = JSON.stringify(api.Properties?.CorsConfiguration?.AllowOrigins);
    expect(allowOrigins).toContain("HasPublicSiteOrigins");
    expect(allowOrigins).toContain("Fn::If");
    const conditions = template.toJSON().Conditions as Record<string, unknown>;
    expect(conditions.HasPublicSiteOrigins).toBeDefined();
  });
});

describe("Evolve Sprouts finance mirror", () => {
  test("HasEvolvesproutsDataApi requires the cluster and a read-only secret", () => {
    const cond = template.toJSON().Conditions.HasEvolvesproutsDataApi;
    const serialized = JSON.stringify(cond);
    expect(serialized).toContain("EvolvesproutsClusterArn");
    expect(serialized).toContain("EvolvesproutsDbSecretArn");
    expect(serialized).toContain("EvolvesproutsDbSecretName");
    expect(template.toJSON().Parameters.EvolvesproutsDbSecretName.Default).toBe("");
  });

  test("routes the read-only book, summary, and sync behind the admin JWT", () => {
    const routes = Object.values(resourcesOfType("AWS::ApiGatewayV2::Route"));
    const keys = routes
      .map((r) => String(r.Properties?.RouteKey))
      .filter((key) => key.includes("/evolvesprouts"))
      .sort();
    expect(keys).toEqual([
      "GET /v1/admin/evolvesprouts",
      "GET /v1/admin/evolvesprouts/summary",
      "POST /v1/admin/evolvesprouts/sync",
    ]);
    for (const route of routes) {
      if (!String(route.Properties?.RouteKey).includes("/evolvesprouts")) continue;
      expect(route.Properties?.AuthorizationType).toBe("JWT");
    }
  });

  test("enables the HTTP endpoint without applying SQL", () => {
    const custom = Object.entries(resources).filter(
      ([, r]) => r.Type === "Custom::AWS" || r.Type === "AWS::CloudFormation::CustomResource"
    );
    const enables = custom.filter(([, r]) =>
      JSON.stringify(r.Properties ?? {}).includes("enableHttpEndpoint")
    );
    expect(enables).toHaveLength(2);
    expect(enables[0]?.[1].Condition).toBe("HasSiutindeiDataApi");
    expect(enables[1]?.[1].Condition).toBe("HasEvolvesproutsDataApi");

    const schemas = custom.filter(([id]) => id.includes("ReceivablesSchema"));
    expect(schemas).toHaveLength(1);
    expect(schemas[0]?.[1].Condition).toBe("HasSiutindeiDataApi");

    const httpFns = Object.entries(resourcesOfType("AWS::Lambda::Function")).filter(([id]) =>
      id.includes("HttpEndpointFn")
    );
    expect(httpFns).toHaveLength(1);
    expect(httpFns[0]?.[1].Condition).toBe("HasEvolvesproutsDataApi");
    expect(httpFns[0]?.[1].Properties?.Environment?.Variables?.DATA_API_APPLY_SQL).toBe("false");
    const skipped = (httpFns[0]?.[1].Metadata?.checkov?.skip ?? []).map((item) => item.id);
    expect(skipped).toEqual(expect.arrayContaining(["CKV_AWS_115", "CKV_AWS_117"]));
  });

  test("AdminApiFn can run statements and read only the resolved secret", () => {
    const [policy] = findPoliciesByConstructId("AdminEvolvesproutsDataApiPolicy");
    const statements = policyStatements(policy!);
    const actions = statements.flatMap((s) => asArray<string>(s.Action));
    expect(actions).toContain("rds-data:ExecuteStatement");
    expect(actions).not.toContain("rds-data:BatchExecuteStatement");
    expect(actions).toContain("secretsmanager:GetSecretValue");

    const adminFn = Object.entries(resourcesOfType("AWS::Lambda::Function")).find(([id]) =>
      id.startsWith("AdminApiFn")
    );
    const env = adminFn?.[1].Properties?.Environment?.Variables ?? {};
    expect(env.EVOLVESPROUTS_DB_NAME).toBeUndefined();
    expect(env.EVOLVESPROUTS_DB_SECRET_ARN).toEqual({
      "Fn::If": ["HasEvolvesproutsDataApi", expect.anything(), ""],
    });
  });

  test("AdminApiFn environment stays under the Lambda 4 KB cap", () => {
    const adminFn = Object.entries(resourcesOfType("AWS::Lambda::Function")).find(([id]) =>
      id.startsWith("AdminApiFn")
    );
    const env = (adminFn?.[1].Properties?.Environment?.Variables ?? {}) as Record<string, unknown>;
    const parameters = template.toJSON().Parameters as Record<string, { Default?: unknown }>;
    const production = productionParamValues();
    const bytes = Object.entries(env).reduce(
      (sum, [key, value]) => sum + key.length + cfnStringBytes(value, parameters, production),
      0
    );
    // Deploy #503 measured 4216 bytes and Lambda rejected it (limit 4096).
    expect(bytes).toBeLessThanOrEqual(3600);
    expect(env.GITHUB_READ_TOKEN_SECRET_ARN).toBe(
      "lxsoftware-admin-siutindei-board-github-token"
    );
    expect(env.BOARD_IMPORTER_CREDENTIALS_SECRET_ARN).toBe(
      "lxsoftware-admin-siutindei-board-importer-credentials"
    );
    expect(env.NEWSLETTER_CONFIG_SET).toBeUndefined();
    expect(env.ASSET_MAX_BYTES).toBeUndefined();
    expect(env.PARSE_JOB_TTL_SECONDS).toBeUndefined();
  });

  test("nightly mirror and the endpoint refresh are conditioned; refresh does not apply SQL", () => {
    const schedules = Object.values(resourcesOfType("AWS::Scheduler::Schedule"));
    const mirror = schedules.find(
      (s) => s.Properties?.Name === "lxsoftware-admin-evolvesprouts-finance-mirror"
    );
    expect(mirror).toBeDefined();
    expect(mirror?.Condition).toBe("HasEvolvesproutsDataApi");
    expect(JSON.stringify(mirror?.Properties?.ScheduleExpression ?? "")).toContain("45");
    expect(JSON.stringify(mirror?.Properties?.Target?.Input ?? "")).toContain(
      "evolvesprouts_finance_mirror"
    );
    const ensure = schedules.find(
      (s) => s.Properties?.Name === "lxsoftware-admin-evolvesprouts-data-api-ensure"
    );
    expect(ensure?.Condition).toBe("HasEvolvesproutsDataApi");
    const input = JSON.stringify(ensure?.Properties?.Target?.Input ?? "");
    expect(input).toContain("data_api_ensure");
    expect(input).toContain("false");
  });

  test("Data API scheduler roles are inside the conditioned construct", () => {
    const roles = Object.entries(resourcesOfType("AWS::IAM::Role")).filter(([id]) =>
      id.includes("EnsureScheduleRole")
    );
    expect(roles.length).toBeGreaterThanOrEqual(2);
    for (const [id, role] of roles) {
      if (id.includes("EvolvesproutsDataApi")) {
        expect(role.Condition).toBe("HasEvolvesproutsDataApi");
      }
      if (id.includes("SiutindeiDataApi")) {
        expect(role.Condition).toBe("HasSiutindeiDataApi");
      }
    }
    const dangling = Object.entries(resources).filter(([, r]) => {
      if (r.Type !== "AWS::IAM::Policy" || r.Condition) {
        return false;
      }
      return JSON.stringify(r.Properties ?? {}).includes("EvolvesproutsDataApiHttpEndpointFn");
    });
    expect(dangling).toEqual([]);
  });
});
