import { OPENROUTER_APPS } from "../../lib/contracts/generated";
import { formatUsageCost } from "../../lib/boardModel";
import type { OpenRouterUsagePayload } from "../../lib/openrouterUsage";
import { defaultOpenRouterUsageMonth } from "../../lib/usageMonth";
import { useOpenRouterUsage } from "../../hooks/useOpenRouterUsage";
import { useUsageMonth } from "../../hooks/useUsageMonth";
import { UsageBillCard } from "./UsageBillCard";

export function OpenRouterUsageCard() {
  const { months, month, setMonthKey } = useUsageMonth(
    defaultOpenRouterUsageMonth,
  );
  const query = useOpenRouterUsage(month.from, month.to);
  return (
    <UsageBillCard
      title="OpenRouter"
      monthAriaLabel="OpenRouter month"
      month={month}
      months={months}
      onMonthChange={setMonthKey}
      isLoading={query.isPending}
      loadingMessage="Loading OpenRouter usage…"
      isError={query.isError}
      errorMessage="Could not load OpenRouter usage. LX Software still pays the invoice; tag sibling apps until this endpoint is available."
      emptyMessage="No OpenRouter usage recorded yet."
    >
      {query.data ? (
        <OpenRouterUsageBody data={query.data} isCurrent={month.isCurrent} />
      ) : null}
    </UsageBillCard>
  );
}

function OpenRouterUsageBody({
  data,
  isCurrent,
}: {
  readonly data: OpenRouterUsagePayload;
  readonly isCurrent: boolean;
}) {
  const metered = data.apps.filter((app) => app.meteredHere || (app.cost ?? 0) > 0);
  const siblings = data.apps.filter((app) => !app.meteredHere);
  const catalogSiblings =
    siblings.length > 0 ? siblings : OPENROUTER_APPS.filter((app) => !app.meteredHere);
  const periodLabel = isCurrent ? "UTC month-to-date" : "UTC month";
  return (
    <>
      <p className="small text-muted">
        {data.payer.label} pays the OpenRouter invoice. {periodLabel} (
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
            Same LX Software OpenRouter account. Mint a named key (
            <code>lxsoftware:{"{app-id}"}</code>) and store it in that
            product&apos;s secret. On every chat-completions request send{" "}
            <code>HTTP-Referer</code>, <code>X-OpenRouter-Title</code>,{" "}
            <code>X-OpenRouter-App-Visibility: hidden</code>, and body{" "}
            <code>user</code> as <code>{"{app-id}:{workload}"}</code> (no PII).
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
                  title <code>{app.title}</code> · key{" "}
                  <code>{app.keyName || `lxsoftware:${app.id}`}</code> · user{" "}
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
