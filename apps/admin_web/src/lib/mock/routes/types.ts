export type MockCtx = {
  readonly method: string;
  readonly url: URL;
  readonly path: string;
  readonly init: RequestInit;
};

export type MockRoute = {
  readonly method?: string;
  readonly pattern: RegExp;
  readonly handler: (ctx: MockCtx) => Response | null;
};

export function firstMockRoute(routes: readonly MockRoute[], ctx: MockCtx): Response | null {
  for (const route of routes) {
    if (route.method && route.method !== ctx.method) continue;
    if (!route.pattern.test(ctx.path)) continue;
    const hit = route.handler(ctx);
    if (hit) return hit;
  }
  return null;
}
