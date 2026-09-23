import { formatUsageCost } from "../../lib/boardModel";
import type {
  OpenRouterUsageApp,
  OpenRouterUsagePayload,
  OpenRouterUsagePull,
} from "../../lib/openrouterUsage";
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
      errorMessage="Could not load OpenRouter usage. LX Software still pays the invoice."
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
  const shown = data.apps.filter(showApp);
  const meteredCalls = shown
    .filter((app) => app.meteredHere)
    .reduce((sum, app) => sum + (app.calls ?? 0), 0);
  const periodLabel = isCurrent ? "UTC month-to-date" : "UTC month";
  return (
    <>
      <p className="small text-muted">
        {data.payer.label} pays the OpenRouter invoice. {periodLabel} (
        {data.from} – {data.to}). Total {formatUsageCost(data.total.cost)}.{" "}
        {meteredCalls} calls metered in this admin. Named keys are pulled
        from OpenRouter. Other is Chat and any spend that is not on an API
        key. The current UTC day&apos;s call count is added after Activity
        closes that day.
      </p>
      <PullNotice pull={data.pull} />
      {shown.length === 0 ? (
        <p className="small text-muted">No OpenRouter usage recorded for this range.</p>
      ) : (
        <ul className="list-unstyled mb-0 small">
          {shown.map((app) => (
            <AppSpend key={app.id} app={app} pull={data.pull} />
          ))}
        </ul>
      )}
    </>
  );
}

function AppSpend({
  app,
  pull,
}: {
  readonly app: OpenRouterUsageApp;
  readonly pull: OpenRouterUsagePull | null | undefined;
}) {
  const note = siblingNote(app, pull);
  const owners =
    app.ingestUsage && !app.meteredHere
      ? app.owners.filter((owner) => owner.id !== app.id)
      : app.owners;
  return (
    <li className="mb-2">
      <div className="d-flex justify-content-between gap-3">
        <strong>{app.label}</strong>
        <span>{formatUsageCost(app.cost)}</span>
      </div>
      {note ? <div className="text-muted">{note}</div> : null}
      {owners.length > 0 ? (
        <ul className="list-unstyled ms-2 mb-0 text-muted">
          {owners.map((owner) => (
            <li key={owner.id} className="d-flex justify-content-between gap-3">
              <span>{owner.label}</span>
              <span>
                {formatUsageCost(owner.cost)} · {owner.calls ?? 0} calls
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function PullNotice({ pull }: { readonly pull: OpenRouterUsagePull | null | undefined }) {
  if (pull?.ok) return null;
  const reason = pull?.reason;
  const message =
    reason === "management_key_rejected"
      ? "OpenRouter rejected the management key on the admin secret, so sibling spend is not updating."
      : reason === "http_error"
        ? "The last OpenRouter pull failed. Saved days are still shown."
        : reason === "partial"
          ? "The last OpenRouter pull was incomplete. Saved days are still shown."
          : "Sibling spend stays at USD 0.00 until the admin OpenRouter secret includes a management key (OpenRouter Management API key). The hourly pull reads Activity for each named sibling key.";
  return (
    <p className="small text-warning-emphasis" role="status">
      {message}
    </p>
  );
}

function showApp(app: OpenRouterUsageApp): boolean {
  if (app.id === "openrouter-other" || app.id.startsWith("or-key:")) {
    return (app.cost ?? 0) > 0;
  }
  return app.meteredHere || app.ingestUsage || (app.cost ?? 0) > 0;
}

function siblingNote(
  app: OpenRouterUsageApp,
  pull: OpenRouterUsagePull | null | undefined,
): string | null {
  if (!app.ingestUsage || app.meteredHere) return null;
  const reason = pull?.reason;
  if (!pull || reason === "management_key_missing" || reason === "management_key_rejected") {
    return "Waiting for the first OpenRouter pull.";
  }
  if (reason === "http_error") {
    return "Last pull failed. Showing saved days.";
  }
  if (app.id === "openrouter-other") {
    return "OpenRouter Chat and spend that is not on an API key.";
  }
  const status = pull.apps.find((row) => row.id === app.id)?.status;
  if (status === "key_not_found") {
    return `Named key ${app.keyName} is not on the OpenRouter account yet.`;
  }
  if (status === "error") {
    return "Last pull failed for this key. Showing saved days.";
  }
  if (status === "no_usage" || (app.cost ?? 0) === 0) {
    return "Pulled from OpenRouter · no spend on this key yet.";
  }
  return "Pulled from OpenRouter";
}
