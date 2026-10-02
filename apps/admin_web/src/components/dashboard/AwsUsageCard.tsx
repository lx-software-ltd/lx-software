import { useMutation } from "@tanstack/react-query";
import { AWS_BILLING_COST_ALLOCATION_TAGS } from "../../lib/contracts/generated";
import { formatUsageCost } from "../../lib/boardModel";
import type { AwsBillingPayload } from "../../lib/awsBilling";
import { defaultAwsUsageMonth } from "../../lib/usageMonth";
import { downloadAwsUsagePdfMutationOptions, useAwsUsage } from "../../hooks/useAwsUsage";
import { useUsageMonth } from "../../hooks/useUsageMonth";
import { UsageBillCard } from "./UsageBillCard";

export function AwsUsageCard() {
  const { months, month, setMonthKey } = useUsageMonth(defaultAwsUsageMonth);
  const query = useAwsUsage(month.from, month.to);
  return (
    <UsageBillCard
      title="AWS"
      monthAriaLabel="AWS month"
      month={month}
      months={months}
      onMonthChange={setMonthKey}
      isLoading={query.isPending}
      loadingMessage="Loading AWS cost split…"
      isError={query.isError}
      errorMessage="Could not load the AWS cost split. Cost Explorer needs the Organization and Project cost-allocation tags."
      emptyMessage="No AWS cost data yet."
    >
      {query.data ? <AwsUsageBody data={query.data} /> : null}
    </UsageBillCard>
  );
}

function shareLabel(share: number): string {
  return `${(share * 100).toFixed(1)}%`;
}

function AwsUsageBody({ data }: { readonly data: AwsBillingPayload }) {
  const download = useMutation(downloadAwsUsagePdfMutationOptions());
  const tags = data.costAllocationTags.length
    ? data.costAllocationTags.join(" + ")
    : AWS_BILLING_COST_ALLOCATION_TAGS.join(" + ");

  return (
    <>
      <p className="small text-muted">
        Cost Explorer UnblendedCost for {data.from} – {data.to} is grouped by {tags}.
        Total {formatUsageCost(data.total.usd)}. AWS&apos;s own invoice PDF stays one
        account total; download the allocation PDF for the tagged split.
      </p>
      <ul className="list-unstyled mb-3 small">
        {data.companies.map((company) => (
          <li key={company.id} className="mb-2">
            <div className="d-flex justify-content-between gap-3">
              <strong>{company.label}</strong>
              <span>
                {formatUsageCost(company.usd)} · {shareLabel(company.share)}
              </span>
            </div>
            <div className="admin-share-bar" aria-hidden="true">
              <span style={{ width: `${Math.max(0, Math.min(100, company.share * 100))}%` }} />
            </div>
            {company.projects.length > 0 ? (
              <ul className="list-unstyled ms-2 mb-0 text-muted">
                {company.projects.map((project) => (
                  <li
                    key={project.id}
                    className="d-flex justify-content-between gap-3"
                  >
                    <span>{project.label}</span>
                    <span>{formatUsageCost(project.usd)}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="btn btn-outline-secondary btn-sm mt-auto"
        onClick={() => download.mutate({ from: data.from, to: data.to })}
        disabled={download.isPending}
      >
        {download.isPending ? "Downloading…" : "Download allocation PDF"}
      </button>
      {download.isError ? (
        <p className="small text-danger mb-0 mt-2">Could not download the allocation PDF.</p>
      ) : null}
    </>
  );
}
