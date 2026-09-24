import { useEffect, useMemo, useState } from "react";
import {
  AdminCell,
  AdminDataTable,
  AdminDataTableCellMeta,
  AdminDataTableEmptyRow,
  AdminDialog,
  AdminEditorSection,
  AdminExpandableRow,
  AdminFilterBar,
  AdminFilterField,
  AdminPageHeader,
  AdminRecordTable,
  AdminRowActions,
  ConfirmDialog,
  DateTimeDisplay,
  MoneyAmount,
} from "../components/ui";
import { useExpandedRecord } from "../hooks/useExpandedRecord";
import { useHydrateExpandedRecord } from "../hooks/useHydrateExpandedRecord";
import { clearExpandedParamsExcept } from "../lib/expandedRecord";
import { FinanceDataLoadOrError } from "../components/FinanceDataStatus";
import { useBankOptions, useBankSync } from "../hooks/useBankSync";
import { useFinance } from "../hooks/useFinance";
import { getAdminApiErrorMessage } from "../lib/apiAdminClient";
import {
  BANK_CONNECT_COUNTRIES,
  bankAccountLabel,
  CONSENT_EXPIRY_WARNING_DAYS,
  consentDaysRemaining,
  type BankSyncAccount,
  type BankSyncMapping,
  type BankSyncSession,
} from "../lib/bankSyncModel";

function errorText(err: unknown, fallback: string): string {
  return getAdminApiErrorMessage(err) ?? fallback;
}

/**
 * Consent expiry with an urgency cue. Rendered in the dedicated column on
 * wide screens and repeated under the bank name on phones, so an expiring
 * consent is never hidden by the responsive layout.
 */
function ConsentExpiryNote({
  validUntil,
  showDate = false,
}: {
  readonly validUntil: string | undefined;
  readonly showDate?: boolean;
}) {
  const days = consentDaysRemaining(validUntil);
  if (days === null || !validUntil) {
    return showDate ? <span className="text-muted">—</span> : null;
  }
  const isExpired = days < 0;
  const isExpiring = !isExpired && days <= CONSENT_EXPIRY_WARNING_DAYS;
  const tone = isExpired ? "text-danger fw-semibold" : isExpiring ? "text-warning-emphasis fw-semibold" : "";
  const summary = isExpired
    ? "Consent expired"
    : isExpiring
      ? `Consent expires in ${days} day${days === 1 ? "" : "s"}`
      : `Consent valid ${days} more days`;
  return (
    <span className={tone}>
      {isExpired || isExpiring ? (
        <i className="bi bi-exclamation-triangle-fill me-1" aria-hidden="true" />
      ) : null}
      {showDate ? <DateTimeDisplay iso={validUntil} className={tone} /> : summary}
      {showDate && (isExpired || isExpiring) ? (
        <span className="d-block small">{summary}</span>
      ) : null}
    </span>
  );
}

type LinkedAccountRow = {
  readonly session: BankSyncSession;
  readonly account: BankSyncAccount;
};

export function BankingPage() {
  const {
    state,
    isLoading,
    isError,
    isRefetching,
    refetch,
    error,
    startAuth,
    saveMappings,
    syncNow,
    deleteSession,
  } = useBankSync();
  const { data: financeData } = useFinance();

  const [connectOpen, setConnectOpen] = useState(false);
  const [country, setCountry] = useState("GB");
  const [bankName, setBankName] = useState("");
  const banksQuery = useBankOptions(country);

  const [sessionFilter, setSessionFilter] = useState("");
  const [pendingDisconnect, setPendingDisconnect] = useState<BankSyncSession | null>(null);
  const expandedBank = useExpandedRecord("bank");
  useEffect(() => {
    clearExpandedParamsExcept("bank");
  }, []);
  // null = no local edits; otherwise uid -> accounts-sheet record id ("" = unmapped).
  const [mappingDraft, setMappingDraft] = useState<Record<string, string> | null>(
    null,
  );

  const sessions = useMemo(() => state?.sessions ?? [], [state]);
  const openSession = expandedBank.expandedId
    ? (sessions.find((session) => session.sessionId === expandedBank.expandedId) ?? null)
    : null;
  useHydrateExpandedRecord({
    expandedId: expandedBank.expandedId,
    recordsReady: !isLoading,
    record: openSession,
    apply: () => undefined,
    onMissing: () => expandedBank.request(null, false),
  });
  const mappings = useMemo(() => state?.mappings ?? [], [state]);
  const lastSync = state?.lastSync ?? null;

  const linkedAccounts: readonly LinkedAccountRow[] = useMemo(
    () =>
      sessions.flatMap((session) =>
        session.accounts.map((account) => ({ session, account })),
      ),
    [sessions],
  );

  const savedMappingByUid = useMemo(() => {
    const out: Record<string, string> = {};
    for (const m of mappings) out[m.accountUid] = m.accountRecordId;
    return out;
  }, [mappings]);

  const draftValue = (uid: string): string =>
    mappingDraft?.[uid] ?? savedMappingByUid[uid] ?? "";

  const hasMappingChanges = useMemo(() => {
    if (mappingDraft === null) return false;
    return linkedAccounts.some(
      ({ account }) =>
        (mappingDraft[account.uid] ?? savedMappingByUid[account.uid] ?? "") !==
        (savedMappingByUid[account.uid] ?? ""),
    );
  }, [mappingDraft, linkedAccounts, savedMappingByUid]);

  const filteredSessions = useMemo(() => {
    const needle = sessionFilter.trim().toLowerCase();
    if (!needle) return sessions;
    return sessions.filter((s) =>
      `${s.bankName} ${s.bankCountry}`.toLowerCase().includes(needle),
    );
  }, [sessions, sessionFilter]);

  const recordLabelById = useMemo(() => {
    const out: Record<string, string> = {};
    for (const rec of financeData.accountRecords) {
      out[rec.id] = `${rec.description} (${rec.currency})`;
    }
    return out;
  }, [financeData.accountRecords]);

  const onConnect = () => {
    if (!bankName) return;
    startAuth.mutate(
      { bankName, country },
      {
        onSuccess: ({ url }) => {
          window.location.assign(url);
        },
      },
    );
  };

  const onSaveMappings = () => {
    const next: BankSyncMapping[] = [];
    for (const { account } of linkedAccounts) {
      const recordId = draftValue(account.uid);
      if (recordId) {
        next.push({ accountUid: account.uid, accountRecordId: recordId });
      }
    }
    saveMappings.mutate(next, { onSuccess: () => setMappingDraft(null) });
  };

  const onDeleteSession = (session: BankSyncSession) => {
    deleteSession.mutate(session.sessionId, {
      onSuccess: () => {
        setPendingDisconnect(null);
        if (expandedBank.expandedId === session.sessionId) {
          expandedBank.request(null, false);
        }
      },
    });
  };

  if (isLoading) {
    return <p className="text-muted">Loading bank connections…</p>;
  }

  if (isError) {
    return (
      <div>
        <h1 className="h4 mb-3">Banking</h1>
        <FinanceDataLoadOrError
          isLoading={false}
          isError
          loadErrorMessage={`Could not load bank connections: ${errorText(error, "request failed")}`}
          onRetry={() => void refetch()}
          isRetrying={isRefetching}
        />
      </div>
    );
  }

  return (
    <div>
      <AdminPageHeader
        title="Banking"
        help={
          <>
            Link bank accounts through Enable Banking and refresh the Finance accounts sheet from
            live balances. A scheduled sync also runs daily.
          </>
        }
        actions={
          <>
            <button type="button" className="btn btn-outline-secondary" onClick={() => setConnectOpen(true)}>
              Connect a bank
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => syncNow.mutate()}
              disabled={!state?.enabled || syncNow.isPending || mappings.length === 0}
            >
              {syncNow.isPending ? "Syncing…" : "Sync now"}
            </button>
          </>
        }
      />

      {state && !state.enabled ? (
        <div className="alert alert-warning" role="alert">
          Bank sync is not configured on the backend. Register an Enable
          Banking application with the stack's signing key and deploy with the
          <code className="mx-1">EnableBankingAppId</code>parameter set (see
          docs/deployment/admin-website.md).
        </div>
      ) : null}

      {syncNow.isError ? (
        <div className="alert alert-danger" role="alert">
          Sync failed: {errorText(syncNow.error, "request failed")}
        </div>
      ) : null}
      {deleteSession.isError ? (
        <div className="alert alert-danger" role="alert">
          Disconnect failed: {errorText(deleteSession.error, "request failed")}
        </div>
      ) : null}

      <AdminDialog open={connectOpen} title="Connect a bank" onClose={() => setConnectOpen(false)}>
      <AdminEditorSection
        embedded
        description="You are redirected to the bank's own consent screen and back here afterwards."
        footer={
          <>
            <button
              type="button"
              className="btn btn-primary"
              onClick={onConnect}
              disabled={!state?.enabled || !bankName || startAuth.isPending}
            >
              {startAuth.isPending ? "Starting…" : "Connect"}
            </button>
            {startAuth.isError ? (
              <span className="text-danger small">
                {errorText(startAuth.error, "Could not start authorization")}
              </span>
            ) : null}
          </>
        }
      >
        <div className="row g-3">
          <div className="col-sm-4 col-lg-3">
            <label className="form-label" htmlFor="bank-country">
              Country
            </label>
            <select
              id="bank-country"
              className="form-select"
              value={country}
              onChange={(ev) => {
                setCountry(ev.target.value);
                setBankName("");
              }}
            >
              {BANK_CONNECT_COUNTRIES.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div className="col-sm-8 col-lg-5">
            <label className="form-label" htmlFor="bank-name">
              Bank
            </label>
            <select
              id="bank-name"
              className="form-select"
              value={bankName}
              onChange={(ev) => setBankName(ev.target.value)}
              disabled={!state?.enabled || banksQuery.isLoading}
            >
              <option value="">
                {banksQuery.isLoading ? "Loading banks…" : "Select a bank…"}
              </option>
              {(banksQuery.data?.banks ?? []).map((bank) => (
                <option key={bank.name} value={bank.name}>
                  {bank.name}
                  {bank.beta ? " (beta)" : ""}
                </option>
              ))}
            </select>
            {banksQuery.isError ? (
              <div className="form-text text-danger">
                {errorText(banksQuery.error, "Could not load banks")}
              </div>
            ) : null}
          </div>
        </div>
      </AdminEditorSection>
      </AdminDialog>

      <div className="mb-4">
        <AdminRecordTable
          label="Connected banks"
          filters={
            <AdminFilterBar>
              <AdminFilterField label="Filter" htmlFor="banks-filter">
                <input
                  id="banks-filter"
                  type="search"
                  className="form-control form-control-sm"
                  placeholder="Filter banks…"
                  autoComplete="off"
                  value={sessionFilter}
                  onChange={(ev) => setSessionFilter(ev.target.value)}
                />
              </AdminFilterField>
            </AdminFilterBar>
          }
        >
        <AdminDataTable
          bare
          columns={[
            { key: "bank", header: "Bank" },
            { key: "country", header: "Country", priority: "secondary" },
            { key: "accounts", header: "Accounts", priority: "secondary" },
            { key: "validUntil", header: "Consent valid until", priority: "tertiary" },
            {
              key: "ops",
              header: <span className="visually-hidden">Operations</span>,
              className: "text-end",
            },
          ]}
        >
          {filteredSessions.length === 0 ? (
            <AdminDataTableEmptyRow
              colSpan={5}
              message={
                sessions.length === 0
                  ? "No banks connected yet."
                  : "No banks match the filter."
              }
            />
          ) : (
            filteredSessions.map((session) => (
              <AdminExpandableRow
                key={session.sessionId}
                colSpan={5}
                expanded={expandedBank.expandedId === session.sessionId}
                onToggle={() =>
                  expandedBank.toggle(session.sessionId, false, () => undefined, () => undefined)
                }
                editor={
                  <>
                    <div className="d-md-none">
                      {session.accounts.length === 0 ? (
                        <p className="text-muted small mb-0">No accounts on this consent.</p>
                      ) : (
                        <ul className="list-unstyled mb-0">
                          {session.accounts.map((account) => (
                            <li key={account.uid} className="small">
                              {bankAccountLabel(account)}
                              {account.currency ? (
                                <span className="text-muted"> · {account.currency}</span>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <p className="small mb-0 d-none d-md-block d-lg-none">
                      <ConsentExpiryNote validUntil={session.validUntil} showDate />
                    </p>
                    <p className="small text-muted mb-0 d-none d-lg-block">
                      Connected{" "}
                      {session.createdAt ? <DateTimeDisplay iso={session.createdAt} /> : "—"}.
                    </p>
                  </>
                }
              >
                <AdminCell column="bank">
                  {session.bankName}
                  <AdminDataTableCellMeta>
                    {session.bankCountry}
                    {session.accounts.length
                      ? ` · ${session.accounts.length} account${session.accounts.length === 1 ? "" : "s"}`
                      : ""}
                  </AdminDataTableCellMeta>
                  <AdminDataTableCellMeta until="tertiary">
                    <ConsentExpiryNote validUntil={session.validUntil} />
                  </AdminDataTableCellMeta>
                </AdminCell>
                <AdminCell column="country">{session.bankCountry}</AdminCell>
                <AdminCell column="accounts">
                  {session.accounts.length === 0 ? (
                    <span className="text-muted">none</span>
                  ) : (
                    <ul className="list-unstyled mb-0">
                      {session.accounts.map((account) => (
                        <li key={account.uid} className="small">
                          {bankAccountLabel(account)}
                          {account.currency ? (
                            <span className="text-muted"> · {account.currency}</span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </AdminCell>
                <AdminCell column="validUntil">
                  <ConsentExpiryNote validUntil={session.validUntil} showDate />
                </AdminCell>
                <AdminCell column="ops" className="text-end">
                  <AdminRowActions
                    actions={[
                      {
                        id: "disconnect",
                        label: `Disconnect ${session.bankName}`,
                        iconClassName: "bi bi-trash",
                        danger: true,
                        disabled: deleteSession.isPending,
                        onClick: () => setPendingDisconnect(session),
                      },
                    ]}
                  />
                </AdminCell>
              </AdminExpandableRow>
            ))
          )}
        </AdminDataTable>
        <ConfirmDialog
          open={pendingDisconnect !== null}
          title="Disconnect bank"
          body={
            pendingDisconnect
              ? `Disconnect ${pendingDisconnect.bankName}? Its account mappings are removed and the bank consent is closed.`
              : ""
          }
          confirmLabel="Disconnect"
          tone="danger"
          confirmBusy={deleteSession.isPending}
          onConfirm={() => {
            if (pendingDisconnect) onDeleteSession(pendingDisconnect);
          }}
          onCancel={() => {
            if (!deleteSession.isPending) setPendingDisconnect(null);
          }}
        />
        </AdminRecordTable>
      </div>

      <div className="mb-4">
        <AdminRecordTable
          label="Account mappings"
          filters={
            <>
              <p className="small text-muted mb-2">
                Map each linked bank account to a Finance → Accounts record. Sync writes the live
                balance into the record&apos;s value.
              </p>
              <AdminFilterBar
                trailing={
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={onSaveMappings}
                    disabled={!hasMappingChanges || saveMappings.isPending}
                  >
                    {saveMappings.isPending ? "Saving…" : "Save mappings"}
                  </button>
                }
              />
            </>
          }
        >
          {saveMappings.isError ? (
            <div className="alert alert-danger py-2 small mx-3 mt-3 mb-0" role="alert">
              {errorText(saveMappings.error, "Could not save mappings")}
            </div>
          ) : null}
          {linkedAccounts.length === 0 ? (
            <p className="text-muted small mb-0 px-3 py-3">
              Connect a bank first; its accounts appear here for mapping.
            </p>
          ) : (
            <AdminDataTable
              bare
              tableClassName="admin-table-keep-cols"
              columns={[
                { key: "account", header: "Bank account" },
                { key: "record", header: "Accounts-sheet record" },
              ]}
            >
              {linkedAccounts.map(({ session, account }) => (
                <tr key={account.uid}>
                  <AdminCell column="account">
                    <span className="fw-semibold">{session.bankName}</span>{" "}
                    <span className="text-muted small">
                      {bankAccountLabel(account)}
                      {account.currency ? ` · ${account.currency}` : ""}
                    </span>
                  </AdminCell>
                  <AdminCell column="record" className="admin-mapping-select">
                    <label className="visually-hidden" htmlFor={`mapping-${account.uid}`}>
                      Record for {bankAccountLabel(account)}
                    </label>
                    <select
                      id={`mapping-${account.uid}`}
                      className="form-select form-select-sm"
                      value={draftValue(account.uid)}
                      onChange={(ev) =>
                        setMappingDraft((prev) => ({
                          ...(prev ?? {}),
                          [account.uid]: ev.target.value,
                        }))
                      }
                    >
                      <option value="">Not synced</option>
                      {financeData.accountRecords.map((rec) => (
                        <option key={rec.id} value={rec.id}>
                          {recordLabelById[rec.id]}
                        </option>
                      ))}
                    </select>
                  </AdminCell>
                </tr>
              ))}
            </AdminDataTable>
          )}
        </AdminRecordTable>
      </div>

      <AdminRecordTable
        label="Last sync"
        beforeTable={
          lastSync ? (
            <p className="small text-muted mb-0">
              Ran <DateTimeDisplay iso={lastSync.at} />
            </p>
          ) : (
            <p className="small text-muted mb-0">
              No sync has run yet. Map at least one account, then use Sync now.
            </p>
          )
        }
      >
        {lastSync ? (
          <AdminDataTable
            bare
            columns={[
              { key: "record", header: "Record" },
              { key: "status", header: "Status" },
              { key: "balance", header: "Balance", className: "text-end", headerClassName: "text-end" },
              { key: "details", header: "Details", priority: "secondary" },
            ]}
          >
            {lastSync.results.length === 0 ? (
              <AdminDataTableEmptyRow colSpan={4} message="Nothing was mapped when the sync ran." />
            ) : (
              lastSync.results.map((result) => (
                <tr key={`${result.accountUid}-${result.accountRecordId}`}>
                  <AdminCell column="record">
                    {recordLabelById[result.accountRecordId] ?? result.accountRecordId}
                    <AdminDataTableCellMeta>
                      {result.status === "ok" ? "OK" : "Error"}
                      {result.status === "ok" ? ` · ${result.balanceType}` : ` · ${result.message}`}
                      {result.status === "ok" &&
                      result.balance !== undefined &&
                      result.currency ? (
                        <>
                          {" · "}
                          <MoneyAmount amount={result.balance} currency={result.currency} />
                        </>
                      ) : null}
                    </AdminDataTableCellMeta>
                  </AdminCell>
                  <AdminCell column="status">
                    {result.status === "ok" ? (
                      <span className="badge text-bg-success">OK</span>
                    ) : (
                      <span className="badge text-bg-danger">Error</span>
                    )}
                  </AdminCell>
                  <AdminCell column="balance" className="text-end">
                    {result.status === "ok" &&
                    result.balance !== undefined &&
                    result.currency ? (
                      <MoneyAmount amount={result.balance} currency={result.currency} />
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </AdminCell>
                  <AdminCell column="details" className="small text-muted">
                    {result.status === "ok" ? result.balanceType : result.message}
                  </AdminCell>
                </tr>
              ))
            )}
          </AdminDataTable>
        ) : null}
      </AdminRecordTable>
    </div>
  );
}
