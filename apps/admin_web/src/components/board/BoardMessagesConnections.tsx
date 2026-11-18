import { useEffect, useState } from "react";
import { ConfirmDialog, DateTimeDisplay } from "../ui";
import {
  useBoardMessageStatus,
  useBoardPageSubscribe,
  useBoardWhatsAppConnect,
  useBoardWhatsAppSync,
  type BoardMessageStatus,
} from "../../hooks/useBoardMessages";
import { loadFacebookSdk, startWhatsAppSignup, type FacebookSdk } from "../../lib/board/metaSignup";

const SIGNUP_STORAGE_KEY = "board.messages.metaSignup";

type SignupIds = { readonly appId: string; readonly configId: string };

function readSignupIds(): SignupIds {
  try {
    const stored = JSON.parse(window.localStorage.getItem(SIGNUP_STORAGE_KEY) ?? "{}") as Partial<SignupIds>;
    return { appId: String(stored.appId ?? ""), configId: String(stored.configId ?? "") };
  } catch {
    return { appId: "", configId: "" };
  }
}

function saveSignupIds(ids: SignupIds): void {
  try {
    window.localStorage.setItem(SIGNUP_STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // Private browsing: the ids are typed again next time.
  }
}

type Props = { readonly errorText: (err: unknown) => string | null };

export function BoardMessagesConnections({ errorText }: Props) {
  const status = useBoardMessageStatus();
  const page = useBoardPageSubscribe();
  const data = status.data;

  return (
    <div className="border rounded p-3">
      <div className="row g-3">
        <div className="col-12 col-lg-7">
          <h3 className="h6">WhatsApp</h3>
          {data ? <WhatsAppPanel whatsapp={data.whatsapp} errorText={errorText} /> : <p className="small text-muted mb-0">Loading…</p>}
        </div>
        <div className="col-12 col-lg-5">
          <h3 className="h6">Facebook and Instagram</h3>
          <p className="small text-muted mb-2">
            Subscribes the Page to this app so its messages, replies and comments are delivered. Safe to run again.
          </p>
          <button type="button" className="btn btn-sm btn-outline-primary" disabled={page.isPending} onClick={() => page.mutate()}>
            Subscribe Page
          </button>
          {page.isSuccess ? <span className="small text-success ms-2">Subscribed.</span> : null}
          {page.error ? <p className="text-danger small mb-0 mt-2">{errorText(page.error)}</p> : null}
          <LastDeliveries deliveries={data?.lastDelivery} />
        </div>
      </div>
      {status.error ? <p className="text-danger small mb-0 mt-2">{errorText(status.error)}</p> : null}
    </div>
  );
}

function LastDeliveries({ deliveries }: { readonly deliveries: BoardMessageStatus["lastDelivery"] | undefined }) {
  const rows = [
    { label: "Facebook", at: deliveries?.page },
    { label: "Instagram", at: deliveries?.instagram },
    { label: "WhatsApp", at: deliveries?.whatsapp },
  ];
  return (
    <dl className="small mb-0 mt-3">
      <dt className="text-muted fw-normal">Last message received</dt>
      {rows.map((row) => (
        <dd key={row.label} className="mb-0">
          {row.label}: {row.at ? <DateTimeDisplay iso={row.at} /> : "none yet"}
        </dd>
      ))}
    </dl>
  );
}

function WhatsAppPanel({ whatsapp, errorText }: Props & { readonly whatsapp: BoardMessageStatus["whatsapp"] }) {
  if (!whatsapp.connected) return <WhatsAppConnect errorText={errorText} />;
  return (
    <>
      <p className="small mb-2">
        Connected to <strong>{whatsapp.displayPhoneNumber || `phone number id ${whatsapp.phoneNumberId}`}</strong>
        {whatsapp.verifiedName ? ` (${whatsapp.verifiedName})` : ""}.
      </p>
      {whatsapp.onBusinessApp === false ? (
        <p className="small text-warning-emphasis mb-2">
          Meta reports that this number is not linked to the WhatsApp Business app. Messages typed on the phone will not appear here.
        </p>
      ) : null}
      {whatsapp.disconnectedAt ? (
        <p className="small text-danger mb-2">
          The phone disconnected this app on <DateTimeDisplay iso={whatsapp.disconnectedAt} />.
        </p>
      ) : null}
      <WhatsAppHistory whatsapp={whatsapp} errorText={errorText} />
    </>
  );
}

function WhatsAppHistory({ whatsapp, errorText }: Props & { readonly whatsapp: BoardMessageStatus["whatsapp"] }) {
  const sync = useBoardWhatsAppSync();
  const [confirming, setConfirming] = useState(false);
  const { done, startedAt, contacts, history } = whatsapp.sync;
  const stepError = contacts?.error || history?.error;

  if (done) {
    return (
      <p className="small mb-0">
        History import requested{startedAt ? <> on <DateTimeDisplay iso={startedAt} /></> : null}. Meta delivers it over the next minutes.
        {whatsapp.historyDeclined ? " History sharing was declined on the phone, so nothing will arrive." : ""}
      </p>
    );
  }
  return (
    <>
      <button type="button" className="btn btn-sm btn-outline-primary" disabled={sync.isPending} onClick={() => setConfirming(true)}>
        {startedAt ? "Retry history import" : "Import history"}
      </button>
      {stepError && !sync.error ? <p className="text-danger small mb-0 mt-2">Last attempt: {stepError}</p> : null}
      {sync.error ? <p className="text-danger small mb-0 mt-2">{errorText(sync.error)}</p> : null}
      <ConfirmDialog
        open={confirming}
        title="Import WhatsApp history"
        body="Meta allows this once, and only within 24 hours of connecting the number. Keep the phone unlocked with WhatsApp Business open, and accept history sharing when the phone asks."
        confirmLabel="Import history"
        confirmBusy={sync.isPending}
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          sync.mutate();
        }}
      />
    </>
  );
}

function WhatsAppConnect({ errorText }: Props) {
  const connect = useBoardWhatsAppConnect();
  const [ids, setIds] = useState<SignupIds>(readSignupIds);
  const [sdk, setSdk] = useState<FacebookSdk | null>(null);
  const [notice, setNotice] = useState("");
  const [wabaId, setWabaId] = useState("");
  const [phoneNumberId, setPhoneNumberId] = useState("");
  const appId = ids.appId.trim();
  const configId = ids.configId.trim();

  // Meta's window is a popup, and a popup opened after an await is blocked.
  // The SDK is therefore loaded as soon as the app id is known, before the click.
  useEffect(() => {
    if (!/^\d{5,}$/.test(appId)) return;
    let stale = false;
    loadFacebookSdk(appId).then(
      (loaded) => {
        if (!stale) setSdk(loaded);
      },
      (err: unknown) => {
        if (!stale) setNotice(err instanceof Error ? err.message : "The Facebook SDK did not load.");
      },
    );
    return () => {
      stale = true;
      setSdk(null);
    };
  }, [appId]);

  const openMeta = () => {
    if (!sdk) return;
    saveSignupIds({ appId, configId });
    setNotice("");
    void startWhatsAppSignup(sdk, configId).then((result) => {
      if (result.kind === "finished") connect.mutate({ wabaId: result.wabaId, phoneNumberId: result.phoneNumberId });
      else if (result.kind === "error") setNotice(result.message);
      else setNotice(result.step ? `Meta's window was closed at step ${result.step}. Nothing was connected.` : "Meta's window was closed. Nothing was connected.");
    });
  };

  return (
    <>
      <p className="small text-muted mb-2">
        The number stays on the phone. Connect opens Meta's window: choose "Connect your existing WhatsApp Business app", scan the QR code
        with the phone, and share chat history when asked.
      </p>
      <div className="row g-2 align-items-end">
        <div className="col-12 col-md-4">
          <label className="form-label small" htmlFor="wa-app-id">
            Meta app id
          </label>
          <input
            id="wa-app-id"
            className="form-control form-control-sm"
            inputMode="numeric"
            value={ids.appId}
            onChange={(event) => setIds({ ...ids, appId: event.target.value })}
          />
        </div>
        <div className="col-12 col-md-4">
          <label className="form-label small" htmlFor="wa-config-id">
            Signup configuration id
          </label>
          <input
            id="wa-config-id"
            className="form-control form-control-sm"
            inputMode="numeric"
            value={ids.configId}
            onChange={(event) => setIds({ ...ids, configId: event.target.value })}
          />
        </div>
        <div className="col-12 col-md-4">
          <button type="button" className="btn btn-sm btn-primary" disabled={!sdk || !configId || connect.isPending} onClick={openMeta}>
            Connect WhatsApp
          </button>
        </div>
      </div>
      {notice ? <p className="text-danger small mb-0 mt-2">{notice}</p> : null}
      <details className="small mt-3">
        <summary>Enter the account ids by hand</summary>
        <p className="text-muted mt-2 mb-2">
          For a number Meta has already connected. The board checks both ids with Meta before it reports the number as connected.
        </p>
        <form
          className="row g-2 align-items-end"
          onSubmit={(event) => {
            event.preventDefault();
            connect.mutate({ wabaId: wabaId.trim(), phoneNumberId: phoneNumberId.trim() });
          }}
        >
          <div className="col-12 col-md-4">
            <label className="form-label small" htmlFor="wa-waba">
              Business account id
            </label>
            <input id="wa-waba" className="form-control form-control-sm" inputMode="numeric" value={wabaId} onChange={(event) => setWabaId(event.target.value)} />
          </div>
          <div className="col-12 col-md-4">
            <label className="form-label small" htmlFor="wa-phone">
              Phone number id
            </label>
            <input
              id="wa-phone"
              className="form-control form-control-sm"
              inputMode="numeric"
              value={phoneNumberId}
              onChange={(event) => setPhoneNumberId(event.target.value)}
            />
          </div>
          <div className="col-12 col-md-4">
            <button type="submit" className="btn btn-sm btn-outline-primary" disabled={connect.isPending || !wabaId.trim() || !phoneNumberId.trim()}>
              Check and connect
            </button>
          </div>
        </form>
      </details>
      {connect.error ? <p className="text-danger small mb-0 mt-2">{errorText(connect.error)}</p> : null}
    </>
  );
}
