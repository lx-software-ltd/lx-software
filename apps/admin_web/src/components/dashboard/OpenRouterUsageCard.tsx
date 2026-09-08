import { OPENROUTER_APPS } from "../../lib/contracts/generated";
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
            Could not load OpenRouter usage. LX Software still pays the
            invoice; tag sibling apps until this endpoint is available.
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
  const metered = data.apps.filter((app) => app.meteredHere || (app.cost ?? 0) > 0);
  const siblings = data.apps.filter((app) => !app.meteredHere);
  const catalogSiblings =
    siblings.length > 0 ? siblings : OPENROUTER_APPS.filter((app) => !app.meteredHere);
  return (
    <>
      <p className="small text-muted">
        {data.payer.label} pays the OpenRouter invoice. UTC month-to-date (
        {data.from} – {data.to}) is tagged by app so sibling products can
        share the account. Total {formatUsageCost(data.total.cost)} over{" "}
        {data.total.calls ?? 0} calls metered in this admin.
      </p>
      {metered.every((app) => (app.cost ?? 0) === 0) ? (
        <p className="small text-muted">No usage metered in this admin this month.</p>
      ) : (
        <ul className="list-unstyled mb-3 small">
          {metered.map((app) => (
            <li key={app.id} className="mb-2">
              <div className="d-flex justify-content-between gap-3">
                <strong>{app.label}</strong>
                <span>{formatUsageCost(app.cost)}</span>
              </div>
              {app.owners.length > 0 ? (
                <ul className="list-unstyled ms-2 mb-0 text-muted">
                  {app.owners.map((owner) => (
                    <li
                      key={owner.id}
                      className="d-flex justify-content-between gap-3"
                    >
                      <span>{owner.label}</span>
                      <span>
                        {formatUsageCost(owner.cost)} · {owner.calls ?? 0} calls
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {catalogSiblings.length > 0 ? (
        <div className="small">
          <h3 className="h6">Tag sibling apps</h3>
          <p className="text-muted">
            Same LX Software OpenRouter account. On every chat-completions
            request send <code>HTTP-Referer</code>,{" "}
            <code>X-OpenRouter-Title</code>,{" "}
            <code>X-OpenRouter-App-Visibility: hidden</code>, and body{" "}
            <code>user</code> as <code>{"{app-id}:{workload}"}</code> (no PII).
            Optional named key in the existing secret JSON matching the app id.
          </p>
          <ul className="list-unstyled mb-0">
            {catalogSiblings.map((app) => (
              <li key={app.id} className="mb-2">
                <strong>{app.label}</strong>
                <div className="text-muted">
                  {app.repo ? <code>{app.repo}</code> : null}
                  {app.repo && app.referer ? " · " : null}
                  {app.referer ? <code>{app.referer}</code> : null}
                </div>
                <div className="text-muted">
                  title <code>{app.title}</code> · user{" "}
                  <code>{`${app.id}:{workload}`}</code>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}
