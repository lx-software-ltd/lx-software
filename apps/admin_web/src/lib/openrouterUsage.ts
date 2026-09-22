export type OpenRouterUsageTotals = {
  readonly promptTokens: number;
  readonly completionTokens: number;
  readonly totalTokens: number;
  readonly cost: number;
  readonly calls?: number;
};

export type OpenRouterUsageOwner = OpenRouterUsageTotals & {
  readonly id: string;
  readonly label: string;
};

export type OpenRouterUsageApp = OpenRouterUsageTotals & {
  readonly id: string;
  readonly label: string;
  readonly title: string;
  readonly referer: string;
  readonly repo: string;
  readonly keyName: string;
  readonly meteredHere: boolean;
  readonly ingestUsage: boolean;
  readonly owners: readonly OpenRouterUsageOwner[];
};

export type OpenRouterUsagePullApp = {
  readonly id: string;
  readonly status: string;
  readonly days: number;
};

export type OpenRouterUsagePull = {
  readonly ok: boolean;
  readonly reason: string;
  readonly pulledAt: string;
  readonly apps: readonly OpenRouterUsagePullApp[];
};

export type OpenRouterUsagePayer = {
  readonly id: string;
  readonly label: string;
};

export type OpenRouterUsagePayload = {
  readonly from: string;
  readonly to: string;
  readonly currency: string;
  readonly payer: OpenRouterUsagePayer;
  readonly total: OpenRouterUsageTotals;
  readonly apps: readonly OpenRouterUsageApp[];
  readonly pull?: OpenRouterUsagePull | null;
};

export const OPENROUTER_USAGE_PATH = "/openrouter/usage";
