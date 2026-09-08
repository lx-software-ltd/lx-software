export type OpenRouterUsageTotals = {
  readonly promptTokens: number;
  readonly completionTokens: number;
  readonly totalTokens: number;
  readonly cost: number;
  readonly calls?: number;
};

export type OpenRouterUsageService = OpenRouterUsageTotals & {
  readonly id: string;
  readonly label: string;
};

export type OpenRouterUsageCostCenter = OpenRouterUsageTotals & {
  readonly id: string;
  readonly label: string;
  readonly services: readonly OpenRouterUsageService[];
};

export type OpenRouterUsagePayload = {
  readonly from: string;
  readonly to: string;
  readonly currency: string;
  readonly total: OpenRouterUsageTotals;
  readonly costCenters: readonly OpenRouterUsageCostCenter[];
};

export const OPENROUTER_USAGE_PATH = "/openrouter/usage";
