import { useState } from "react";
import { AWS_BILLING_COST_ALLOCATION_TAGS } from "../../lib/contracts/generated";
import { formatUsageCost } from "../../lib/boardModel";
import { adminFetch } from "../../lib/apiAdminClient";
import {
  AWS_USAGE_PDF_PATH,
  awsUsageQuery,
  type AwsBillingPayload,
} from "../../lib/awsBilling";

export function AwsUsageCard({
  isLoading,
  isError,
  data,
}: {
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly data: AwsBillingPayload | undefined;
}) {
  return (
    <div className="card shadow-sm">
      <div className="card-body">
        <h2 className="h6 text-uppercase text-muted">AWS last invoice</h2>
        {isLoading ? (
          <p className="mb-0 small text-muted">Loading AWS cost split…</p>
        ) : isError ? (
          <p className="mb-0 small text-danger">
            Could not load the AWS cost split. LX Software still pays the
            account invoice; Cost Explorer needs the Organization and Project
            cost-allocation tags.
          </p>
        ) : data ? (
          <AwsUsageBody data={data} />
        ) : (
          <p className="mb-0 small text-muted">No AWS cost data yet.</p>
        )}
      </div>
    </div>
  );
}

function shareLabel(share: number): string {
  return `${(share * 100).toFixed(1)}%`;
}

function AwsUsageBody({ data }: { readonly data: AwsBillingPayload }) {
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const tags = data.costAllocationTags.length
    ? data.costAllocationTags.join(" + ")
    : AWS_BILLING_COST_ALLOCATION_TAGS.join(" + ");

  async function downloadPdf() {
    setDownloadError(null);
    setIsDownloading(true);
    try {
      const res = await adminFetch(
        `${AWS_USAGE_PDF_PATH}${awsUsageQuery(data.from, data.to)}`,
      );
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `lx-software-aws-${data.from.slice(0, 7)}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      setDownloadError("Could not download the allocation PDF.");
    } finally {
      setIsDownloading(false);
    }
  }

  return (
    <>
      <p className="small text-muted">
        {data.payer.label} pays the AWS invoice for this account. Cost Explorer
        UnblendedCost for {data.from} – {data.to} is grouped by {tags} so Siu
        Tin Dei, Evolve Sprouts, and LX Software can share the bill. Total{" "}
        {formatUsageCost(data.total.usd)}. AWS&apos;s own invoice PDF stays one
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
        className="btn btn-outline-secondary btn-sm"
        onClick={() => void downloadPdf()}
        disabled={isDownloading}
      >
        {isDownloading ? "Downloading…" : "Download allocation PDF"}
      </button>
      {downloadError ? (
        <p className="small text-danger mb-0 mt-2">{downloadError}</p>
      ) : null}
    </>
  );
}
