export type AwsBillingProject = {
  readonly id: string;
  readonly label: string;
  readonly usd: number;
};

export type AwsBillingCompany = {
  readonly id: string;
  readonly label: string;
  readonly usd: number;
  readonly share: number;
  readonly projects: readonly AwsBillingProject[];
};

export type AwsBillingPayload = {
  readonly from: string;
  readonly to: string;
  readonly currency: string;
  readonly payer: { readonly id: string; readonly label: string };
  readonly source: string;
  readonly costAllocationTags: readonly string[];
  readonly total: { readonly usd: number };
  readonly companies: readonly AwsBillingCompany[];
};

export const AWS_USAGE_PATH = "/aws/usage";
export const AWS_USAGE_PDF_PATH = "/aws/usage.pdf";

export function awsUsageQuery(fromDay?: string, toDay?: string): string {
  const params = new URLSearchParams();
  if (fromDay) params.set("from", fromDay);
  if (toDay) params.set("to", toDay);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}
