import { OPENROUTER_APPS } from "../../lib/contracts/generated";
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
  const shown = data.apps.filter(
    (app) => app.meteredHere || app.ingestUsage || (app.cost ?? 0) > 0,
  );
  const tagOnly = data.apps.filter(
    (app) => !app.meteredHere && !app.ingestUsage && (app.cost ?? 0) === 0,
  );
  const catalogTagOnly =
    tagOnly.length > 0
      ? tagOnly
      : OPENROUTER_APPS.filter((app) => !app.meteredHere && !app.ingestUsage);
  const periodLabel = isCurrent ? "UTC month-to-date" : "UTC month";
  return (
    <>
      <p className="small text-muted">
        {data.payer.label} pays the OpenRouter invoice. {periodLabel} (
        {data.from} – {data.to}) includes calls metered in this admin and
        sibling spend pulled hourly from OpenRouter. Total{" "}
        {formatUsageCost(data.total.cost)} over {data.total.calls ?? 0} calls.
      </p>
      <PullNotice pull={data.pull} />
      {shown.length === 0 ? (
        <p className="small text-muted">No OpenRouter usage recorded for this range.</p>
      ) : (
        <ul className="list-unstyled mb-3 small">
          {shown.map((app) => (
            <AppSpend key={app.id} app={app} pull={data.pull} />
          ))}
        </ul>
      )}
      {catalogTagOnly.length > 0 ? (
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
            {catalogTagOnly.map((app) => (
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
      : reason === "partial"
        ? "The last OpenRouter pull was incomplete. Saved days are still shown."
        : "Sibling spend stays at USD 0.00 until the admin OpenRouter secret includes a management key (OpenRouter Management API key). The hourly pull reads Activity for each named sibling key.";
  return (
    <p className="small text-warning-emphasis" role="status">
      {message}
    </p>
  );
}

function siblingNote(
  app: OpenRouterUsageApp,
  pull: OpenRouterUsagePull | null | undefined,
): string | null {
  if (!app.ingestUsage || app.meteredHere) return null;
  const status = pull?.apps.find((row) => row.id === app.id)?.status;
  if (status === "key_not_found") {
    return `Named key ${app.keyName} is not on the OpenRouter account yet.`;
  }
  if (status === "error") {
    return "Last pull failed for this key. Showing saved days.";
  }
  if (status === "no_usage" || (app.cost ?? 0) === 0) {
    return "Pulled from OpenRouter · no spend on this key yet.";
  }
  const calls = app.calls ?? 0;
  return calls > 0 ? `Pulled from OpenRouter · ${calls} calls` : "Pulled from OpenRouter";
}
