import { ROUTES, type AdminApiRoute } from "./admin-api-routes";
import { LIVE_ROUTES } from "./admin-api-live-routes";

/**
 * Which slice of the cutover the stack deploys.
 *
 * Stage 0 is the live table. Odd stages add the next batch (at most 70
 * method keys). Even stages delete only the old keys whose replacements
 * were added in the previous stage. The last stage equals ROUTES.
 * Later deploys change only this number, until the last one also narrows
 * the Lambda legacy rewrite back to the forever keepers.
 */
export const ROUTE_STAGE = 3;

const MAX_CREATED = 70;

/** Paths that stay on the gateway for this whole cutover. */
const KEEPER_PATHS = new Set([
  "/health",
  "/webhooks/meta",
  "/webhooks/meta/siutindei",
  "/public/outreach/unsubscribe/{token}",
  "/public/newsletter/confirm/{token}",
  "/public/newsletter/unsubscribe/{token}",
  "/public/siu-tin-dei/board",
  "/public/siu-tin-dei/board/{proxy+}",
]);

const EXACT_RENAMES: Readonly<Record<string, string>> = {
  "/aws/usage.pdf": "/v1/admin/aws/usage/pdf",
  "/fx/v2/rates": "/v1/admin/fx/rates",
  "/public/fx/v2/rates": "/v1/partner/fx/rates",
  "/public/newsletter/subscribe": "/v1/public/newsletter/subscribe",
};

/** Longer prefixes first so /public/lx-software is not left for a shorter rule. */
const PREFIX_RENAMES: readonly (readonly [string, string])[] = [
  ["/public/lx-software", "/v1/partner/lx-software"],
  ["/public/finance", "/v1/partner/finance"],
  ["/public/records", "/v1/partner/records"],
  ["/siu-tin-dei", "/v1/admin/siutindei"],
  ["/evolve-sprouts", "/v1/admin/evolvesprouts"],
  ["/lx-software", "/v1/admin/lx-software"],
  ["/openrouter", "/v1/admin/openrouter"],
  ["/assets", "/v1/admin/assets"],
  ["/records", "/v1/admin/records"],
  ["/finance", "/v1/admin/finance"],
  ["/banking", "/v1/admin/banking"],
  ["/aws", "/v1/admin/aws"],
  ["/me", "/v1/admin/me"],
];

export interface RouteCutoverPair {
  readonly oldKey: string;
  readonly newKey: string;
}

export function routeMethodKeys(routes: readonly AdminApiRoute[]): string[] {
  const keys: string[] = [];
  for (const route of routes) {
    for (const method of route.methods) {
      keys.push(`${method} ${route.path}`);
    }
  }
  return keys;
}

function snakeParams(path: string): string {
  return path.replace(/\{([^}]+)\}/g, (_match, name: string) => {
    const snake = name.replace(/[A-Z]/g, (letter: string) => `_${letter.toLowerCase()}`);
    return `{${snake}}`;
  });
}

/** Contract path for a live path, or null when the live path is a keeper. */
export function contractPathForLive(path: string): string | null {
  if (KEEPER_PATHS.has(path)) {
    return null;
  }
  const exact = EXACT_RENAMES[path];
  if (exact) {
    return exact;
  }
  for (const [oldPath, newPath] of PREFIX_RENAMES) {
    if (path === oldPath || path.startsWith(`${oldPath}/`)) {
      return snakeParams(newPath + path.slice(oldPath.length));
    }
  }
  throw new Error(`no contract path for live route ${path}`);
}

/**
 * Admin console first, then the board in file order, then LinkedIn, Resume,
 * and partner replacements. Newsletter subscribe is a replacement (it has an
 * old key). Net-new keys are not in this scale.
 */
function replacementPriority(path: string): number {
  if (path.startsWith("/v1/admin/siutindei/board")) return 6;
  if (path.startsWith("/v1/admin/siutindei")) return 2;
  if (path.startsWith("/v1/admin/evolvesprouts")) return 3;
  if (path.startsWith("/v1/admin/lx-software/linkedin")) return 7;
  if (path.startsWith("/v1/admin/lx-software/resume")) return 8;
  if (path === "/v1/admin/lx-software" || path.startsWith("/v1/admin/lx-software/")) return 4;
  if (path.startsWith("/v1/admin/banking")) return 5;
  if (path.startsWith("/v1/admin/")) return 1;
  if (path.startsWith("/v1/partner/")) return 9;
  if (path === "/v1/public/newsletter/subscribe") return 10;
  throw new Error(`replacement path has no priority: ${path}`);
}

interface CutoverPlan {
  readonly pairs: readonly RouteCutoverPair[];
  readonly keeperKeys: readonly string[];
  readonly netNewKeys: readonly string[];
  readonly addBatches: readonly (readonly AdminApiRoute[])[];
  readonly deleteBatches: readonly (readonly AdminApiRoute[])[];
  readonly finalStage: number;
}

function indexByKey(routes: readonly AdminApiRoute[]): Map<string, AdminApiRoute> {
  const byKey = new Map<string, AdminApiRoute>();
  for (const route of routes) {
    for (const key of routeMethodKeys([route])) {
      if (byKey.has(key)) {
        throw new Error(`duplicate method key ${key}`);
      }
      byKey.set(key, route);
    }
  }
  return byKey;
}

function buildPlan(): CutoverPlan {
  const contractByKey = indexByKey(ROUTES);
  const pairs: RouteCutoverPair[] = [];
  const pairEntries: { live: AdminApiRoute; contract: AdminApiRoute; newKey: string }[] = [];
  const keeperKeys: string[] = [];
  const seenLive = new Set<string>();

  for (const live of LIVE_ROUTES) {
    const mapped = contractPathForLive(live.path);
    for (const method of live.methods) {
      const oldKey = `${method} ${live.path}`;
      if (seenLive.has(oldKey)) {
        throw new Error(`duplicate live method key ${oldKey}`);
      }
      seenLive.add(oldKey);
      if (mapped === null) {
        if (!contractByKey.has(oldKey)) {
          throw new Error(`keeper missing from the contract: ${oldKey}`);
        }
        keeperKeys.push(oldKey);
        continue;
      }
      const newKey = `${method} ${mapped}`;
      const contract = contractByKey.get(newKey);
      if (!contract) {
        throw new Error(`no contract route for ${oldKey} -> ${newKey}`);
      }
      pairs.push({ oldKey, newKey });
      pairEntries.push({ live, contract, newKey });
    }
  }

  const pairedNew = new Set(pairs.map((pair) => pair.newKey));
  const replacements: AdminApiRoute[] = [];
  const netNew: AdminApiRoute[] = [];
  for (const route of ROUTES) {
    const keys = routeMethodKeys([route]);
    if (KEEPER_PATHS.has(route.path)) {
      continue;
    }
    if (keys.every((key) => pairedNew.has(key))) {
      replacements.push(route);
      continue;
    }
    if (keys.every((key) => !pairedNew.has(key))) {
      netNew.push(route);
      continue;
    }
    throw new Error(`route entry mixes paired and net-new methods: ${route.path}`);
  }

  const ordered = [...replacements].sort(
    (left, right) => replacementPriority(left.path) - replacementPriority(right.path) || 0,
  );
  const replacementBatches: AdminApiRoute[][] = [];
  let batch: AdminApiRoute[] = [];
  let count = 0;
  for (const route of ordered) {
    const methods = route.methods.length;
    if (count + methods > MAX_CREATED && batch.length > 0) {
      replacementBatches.push(batch);
      batch = [];
      count = 0;
    }
    if (methods > MAX_CREATED) {
      throw new Error(`route entry has ${methods} methods: ${route.path}`);
    }
    batch.push(route);
    count += methods;
  }
  if (batch.length > 0) {
    replacementBatches.push(batch);
  }

  const batchOf = new Map<AdminApiRoute, number>();
  replacementBatches.forEach((group, index) => {
    for (const route of group) {
      batchOf.set(route, index);
    }
  });
  const deleteAt = new Map<AdminApiRoute, number>();
  for (const entry of pairEntries) {
    const index = batchOf.get(entry.contract);
    if (index === undefined) {
      throw new Error(`paired route was not batched: ${entry.newKey}`);
    }
    const previous = deleteAt.get(entry.live);
    if (previous === undefined || index > previous) {
      deleteAt.set(entry.live, index);
    }
  }
  const deleteBatches = replacementBatches.map(() => [] as AdminApiRoute[]);
  for (const live of LIVE_ROUTES) {
    const index = deleteAt.get(live);
    if (index !== undefined) {
      deleteBatches[index].push(live);
    }
  }

  const keeper = new Set(keeperKeys);
  const liveKeys = new Set(routeMethodKeys(LIVE_ROUTES));
  const contractKeys = new Set(routeMethodKeys(ROUTES));
  const pairedOld = new Set(pairs.map((pair) => pair.oldKey));
  const netNewKeys = routeMethodKeys(netNew);
  const net = new Set(netNewKeys);
  for (const key of liveKeys) {
    if (!keeper.has(key) && !pairedOld.has(key)) {
      throw new Error(`live key is neither a keeper nor paired: ${key}`);
    }
  }
  for (const key of contractKeys) {
    const classes = [keeper.has(key), pairedNew.has(key), net.has(key)].filter(Boolean).length;
    if (classes !== 1) {
      throw new Error(`contract key ${key} is in ${classes} classes`);
    }
  }
  if (keeper.size !== 15) {
    throw new Error(`expected 15 keeper methods, found ${keeper.size}`);
  }

  return {
    pairs,
    keeperKeys,
    netNewKeys,
    addBatches: [...replacementBatches, netNew],
    deleteBatches,
    finalStage: replacementBatches.length * 2 + 1,
  };
}

const PLAN = buildPlan();

/** Last stage. Its method keys equal ROUTES. */
export const FINAL_ROUTE_STAGE = PLAN.finalStage;

export function routeCutoverPairs(): readonly RouteCutoverPair[] {
  return PLAN.pairs;
}

export function routeKeeperKeys(): readonly string[] {
  return PLAN.keeperKeys;
}

export function routeNetNewKeys(): readonly string[] {
  return PLAN.netNewKeys;
}

/**
 * Gateway routes for one stage.
 *
 * Odd stages add a batch. Even stages (after 0) only delete old keys from
 * the previous add. Adds and deletes are never in the same stage.
 */
export function routesForStage(stage: number): readonly AdminApiRoute[] {
  if (!Number.isInteger(stage) || stage < 0 || stage > PLAN.finalStage) {
    throw new Error(`route stage ${stage} is outside 0..${PLAN.finalStage}`);
  }
  if (stage === 0) {
    return LIVE_ROUTES;
  }
  const adds = Math.ceil(stage / 2);
  const deletes = Math.floor(stage / 2);
  const removed = new Set<AdminApiRoute>();
  for (const group of PLAN.deleteBatches.slice(0, deletes)) {
    for (const route of group) {
      removed.add(route);
    }
  }
  const kept = LIVE_ROUTES.filter((route) => !removed.has(route));
  const added = PLAN.addBatches.slice(0, adds).flat();
  return [...kept, ...added];
}

if (!Number.isInteger(ROUTE_STAGE) || ROUTE_STAGE < 0 || ROUTE_STAGE > FINAL_ROUTE_STAGE) {
  throw new Error(`ROUTE_STAGE ${ROUTE_STAGE} is outside 0..${FINAL_ROUTE_STAGE}`);
}
