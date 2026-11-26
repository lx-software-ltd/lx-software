import { ROUTES, type AdminApiRoute } from "../lib/admin-api-routes";
import { LIVE_ROUTES } from "../lib/admin-api-live-routes";
import {
  FINAL_ROUTE_STAGE,
  ROUTE_STAGE,
  contractPathForLive,
  routeCutoverPairs,
  routeKeeperKeys,
  routeMethodKeys,
  routeRetiredKeys,
  routeNetNewKeys,
  routesForStage,
} from "../lib/admin-api-route-stage";

const KEEPERS = [
  "GET /health",
  "GET /public/outreach/unsubscribe/{token}",
  "POST /public/outreach/unsubscribe/{token}",
  "GET /public/newsletter/confirm/{token}",
  "GET /public/newsletter/unsubscribe/{token}",
  "POST /public/newsletter/unsubscribe/{token}",
];

const RETIRED = [
  "GET /webhooks/meta",
  "POST /webhooks/meta",
  "GET /webhooks/meta/siutindei",
  "POST /webhooks/meta/siutindei",
  "GET /public/siu-tin-dei/board",
  "GET /public/siu-tin-dei/board/{proxy+}",
  "PUT /public/siu-tin-dei/board/{proxy+}",
  "POST /public/siu-tin-dei/board/{proxy+}",
  "DELETE /public/siu-tin-dei/board/{proxy+}",
];

const NET_NEW = [
  "GET /v1/webhooks/meta",
  "POST /v1/webhooks/meta",
  "GET /v1/webhooks/meta/siutindei",
  "POST /v1/webhooks/meta/siutindei",
  "GET /v1/public/outreach/unsubscribe/{token}",
  "POST /v1/public/outreach/unsubscribe/{token}",
  "GET /v1/public/newsletter/confirm/{token}",
  "GET /v1/public/newsletter/unsubscribe/{token}",
  "POST /v1/public/newsletter/unsubscribe/{token}",
  "GET /v1/partner/siutindei/board",
  "GET /v1/partner/siutindei/board/{proxy+}",
  "PUT /v1/partner/siutindei/board/{proxy+}",
  "POST /v1/partner/siutindei/board/{proxy+}",
  "DELETE /v1/partner/siutindei/board/{proxy+}",
];

function signature(route: AdminApiRoute): string {
  const rate = route.throttle?.ThrottlingRateLimit ?? "";
  const burst = route.throttle?.ThrottlingBurstLimit ?? "";
  return `${route.path}|${route.methods.join(",")}|${route.auth}|${rate}|${burst}`;
}

function sortedSignatures(routes: readonly AdminApiRoute[]): string[] {
  return routes.map(signature).sort();
}

describe("HTTP API route cutover stages", () => {
  const stages = Array.from({ length: FINAL_ROUTE_STAGE + 1 }, (_, stage) =>
    routesForStage(stage),
  );
  const keys = stages.map((routes) => new Set(routeMethodKeys(routes)));

  test("stage 0 is the live table and the last stage equals the contract", () => {
    expect(sortedSignatures(routesForStage(0))).toEqual(sortedSignatures(LIVE_ROUTES));
    expect(sortedSignatures(routesForStage(FINAL_ROUTE_STAGE))).toEqual(sortedSignatures(ROUTES));
    expect(routeMethodKeys(routesForStage(FINAL_ROUTE_STAGE))).toHaveLength(225);
    expect(ROUTE_STAGE).toBeGreaterThan(0);
    expect(ROUTE_STAGE).toBeLessThanOrEqual(FINAL_ROUTE_STAGE);
  });

  test("GET /health is the first registered route in every stage", () => {
    for (const routes of stages) {
      expect(routes[0]).toMatchObject({ path: "/health", methods: ["GET"], auth: "none" });
    }
  });

  test("each stage stays within the route quota", () => {
    for (let stage = 0; stage <= FINAL_ROUTE_STAGE; stage += 1) {
      expect(keys[stage].size).toBeLessThanOrEqual(290);
      if (stage === 0) continue;
      const created = [...keys[stage]].filter((key) => !keys[stage - 1].has(key));
      expect(created.length).toBeLessThanOrEqual(70);
      // Odd stages add. Even stages only delete. Never both.
      if (stage % 2 === 1) {
        expect(created.length).toBeGreaterThan(0);
        expect([...keys[stage - 1]].filter((key) => !keys[stage].has(key))).toEqual([]);
      } else {
        expect(created).toEqual([]);
      }
    }
  });

  test("the keepers stay, and the retired paths leave only on the last stage", () => {
    expect([...routeKeeperKeys()].sort()).toEqual([...KEEPERS].sort());
    expect([...routeRetiredKeys()].sort()).toEqual([...RETIRED].sort());
    for (const stageKeys of keys) {
      for (const key of KEEPERS) {
        expect(stageKeys.has(key)).toBe(true);
      }
    }
    for (let stage = 0; stage < FINAL_ROUTE_STAGE; stage += 1) {
      for (const key of RETIRED) {
        expect(keys[stage].has(key)).toBe(true);
      }
    }
    for (const key of RETIRED) {
      expect(keys[FINAL_ROUTE_STAGE].has(key)).toBe(false);
    }
  });

  test("an old key is removed only after its new key was already deployed", () => {
    const pairs = routeCutoverPairs();
    expect(new Set(pairs.map((pair) => pair.oldKey)).size).toBe(pairs.length);
    expect(new Set(pairs.map((pair) => pair.newKey)).size).toBe(pairs.length);
    for (const pair of pairs) {
      let born = -1;
      let gone = -1;
      for (let stage = 0; stage <= FINAL_ROUTE_STAGE; stage += 1) {
        if (born < 0 && keys[stage].has(pair.newKey)) born = stage;
        if (gone < 0 && !keys[stage].has(pair.oldKey)) gone = stage;
      }
      expect(born).toBeGreaterThan(0);
      expect(keys[born].has(pair.oldKey)).toBe(true);
      expect(gone).toBe(born + 1);
      expect(keys[gone].has(pair.newKey)).toBe(true);
    }
  });

  test("every live key is a keeper or paired, and every contract key is paired or net-new", () => {
    const pairs = routeCutoverPairs();
    const pairedOld = new Set(pairs.map((pair) => pair.oldKey));
    const pairedNew = new Set(pairs.map((pair) => pair.newKey));
    const keepers = new Set(KEEPERS);
    const retired = new Set(RETIRED);
    const netNew = new Set(routeNetNewKeys());
    expect([...netNew].sort()).toEqual([...NET_NEW].sort());
    for (const key of routeMethodKeys(LIVE_ROUTES)) {
      expect(keepers.has(key) || retired.has(key) || pairedOld.has(key)).toBe(true);
      expect([keepers.has(key), retired.has(key), pairedOld.has(key)].filter(Boolean)).toHaveLength(1);
    }
    for (const key of routeMethodKeys(ROUTES)) {
      const classes = [keepers.has(key), pairedNew.has(key), netNew.has(key)].filter(Boolean);
      expect(classes).toHaveLength(1);
    }
    const partner = pairs.filter(
      (pair) =>
        pair.newKey.includes(" /v1/partner/") &&
        !pair.newKey.includes("/v1/partner/siutindei/board"),
    );
    expect(partner).toHaveLength(9);
    expect(netNew.has("POST /v1/public/newsletter/subscribe")).toBe(false);
    expect(pairedNew.has("POST /v1/public/newsletter/subscribe")).toBe(true);
  });

  test("non-obvious renames pair one old key to one new key", () => {
    const byOld = new Map(routeCutoverPairs().map((pair) => [pair.oldKey, pair.newKey]));
    expect(byOld.get("GET /aws/usage.pdf")).toBe("GET /v1/admin/aws/usage/pdf");
    expect(byOld.get("GET /fx/v2/rates")).toBe("GET /v1/admin/fx/rates");
    expect(byOld.get("GET /public/fx/v2/rates")).toBe("GET /v1/partner/fx/rates");
    expect(byOld.get("POST /public/newsletter/subscribe")).toBe(
      "POST /v1/public/newsletter/subscribe",
    );
    expect(byOld.get("GET /finance/{house}/parse-statement/jobs/{jobId}")).toBe(
      "GET /v1/admin/finance/{house}/parse-statement/jobs/{job_id}",
    );
    expect(byOld.get("DELETE /banking/sessions/{sessionId}")).toBe(
      "DELETE /v1/admin/banking/sessions/{session_id}",
    );
    expect(byOld.get("PUT /siu-tin-dei/board/members/{personaId}")).toBe(
      "PUT /v1/admin/siutindei/board/members/{persona_id}",
    );
    expect(contractPathForLive("/health")).toBeNull();
    expect(contractPathForLive("/public/siu-tin-dei/board")).toBeNull();
  });

  test("the first add is the admin core, houses, banking, and the start of the board", () => {
    const created = [...keys[1]].filter((key) => !keys[0].has(key));
    expect(created).toHaveLength(70);
    const core = created.filter((key) => {
      const path = key.slice(key.indexOf(" ") + 1);
      return (
        path.startsWith("/v1/admin/") &&
        !path.startsWith("/v1/admin/siutindei") &&
        !path.startsWith("/v1/admin/lx-software") &&
        !path.startsWith("/v1/admin/evolvesprouts") &&
        !path.startsWith("/v1/admin/banking")
      );
    });
    expect(core).toHaveLength(27);
    expect(created.filter((key) => key.includes("/v1/admin/siutindei/parse-statement") || key.endsWith("/v1/admin/siutindei"))).toHaveLength(4);
    expect(created.filter((key) => key.includes("/v1/admin/evolvesprouts"))).toHaveLength(3);
    expect(
      created.filter(
        (key) =>
          key.includes("/v1/admin/lx-software") &&
          !key.includes("/linkedin") &&
          !key.includes("/resume"),
      ),
    ).toHaveLength(4);
    expect(created.filter((key) => key.includes("/v1/admin/banking"))).toHaveLength(7);
    const contractBoard = routeMethodKeys(ROUTES).filter((key) =>
      key.includes("/v1/admin/siutindei/board"),
    );
    const createdBoard = created.filter((key) => key.includes("/v1/admin/siutindei/board"));
    expect(createdBoard.length).toBe(25);
    expect(contractBoard.slice(0, createdBoard.length)).toEqual(createdBoard);
    expect(createdBoard[createdBoard.length - 1]).toBe(
      "POST /v1/admin/siutindei/board/approvals/{approval_id}/reject",
    );
    expect(created.some((key) => key.includes("/linkedin") || key.includes("/resume"))).toBe(false);
    expect(created.some((key) => key.includes("/v1/partner/") || key.includes("/v1/webhooks/"))).toBe(
      false,
    );
  });

  test("the last add is only the net-new keys, then the last stage only deletes", () => {
    const addStage = FINAL_ROUTE_STAGE - 1;
    const created = [...keys[addStage]].filter((key) => !keys[addStage - 1].has(key));
    expect(created.sort()).toEqual([...NET_NEW].sort());
    expect(keys[addStage - 1].size).toBe(220);
    const removed = [...keys[addStage]].filter((key) => !keys[FINAL_ROUTE_STAGE].has(key));
    expect(removed.sort()).toEqual([...RETIRED].sort());
    expect([...keys[FINAL_ROUTE_STAGE]].filter((key) => !keys[addStage].has(key))).toEqual([]);
  });
});
