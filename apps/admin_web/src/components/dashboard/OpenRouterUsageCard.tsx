import { formatUsageCost } from "../../lib/boardModel";
import type { OpenRouterUsagePayload } from "../../lib/openrouterUsage";

export function OpenRouterUsageCard({
  isLoading,
  isError,
  data,
}: {
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly data: OpenRouterUsagePayload | undefined;
}) {
  return (
    <div className="card shadow-sm">
      <div className="card-body">
        <h2 className="h6 text-uppercase text-muted">OpenRouter this month</h2>
        {isLoading ? (
          <p className="mb-0 small text-muted">Loading OpenRouter usage…</p>
        ) : isError ? (
          <p className="mb-0 small text-danger">
            Could not load OpenRouter usage. The invoice still needs a manual
            split until this endpoint is available.
          </p>
        ) : data ? (
          <OpenRouterUsageBody data={data} />
        ) : (
          <p className="mb-0 small text-muted">No OpenRouter usage recorded yet.</p>
        )}
      </div>
    </div>
  );
}

function OpenRouterUsageBody({ data }: { readonly data: OpenRouterUsagePayload }) {
  const centers = data.costCenters;
  return (
    <>
      <p className="small text-muted">
        OpenRouter bills one account. Book these UTC month-to-date amounts (
        {data.from} – {data.to}) onto each statement book or house. Total{" "}
        {formatUsageCost(data.total.cost)} over {data.total.calls ?? 0} calls.
      </p>
      {centers.length === 0 ? (
        <p className="mb-0 small text-muted">No usage this month.</p>
      ) : (
        <ul className="list-unstyled mb-0 small">
          {centers.map((center) => (
            <li key={center.id} className="mb-2">
              <div className="d-flex justify-content-between gap-3">
                <strong>{center.label}</strong>
                <span>{formatUsageCost(center.cost)}</span>
              </div>
              <ul className="list-unstyled ms-2 mb-0 text-muted">
                {center.services.map((service) => (
                  <li
                    key={service.id}
                    className="d-flex justify-content-between gap-3"
                  >
                    <span>{service.label}</span>
                    <span>
                      {formatUsageCost(service.cost)} · {service.calls ?? 0} calls
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
