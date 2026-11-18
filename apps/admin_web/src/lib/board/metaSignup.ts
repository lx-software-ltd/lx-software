/**
 * Meta's Embedded Signup for a number that stays on the WhatsApp Business app
 * ("coexistence"). The window Meta opens reports the account id and the phone
 * number id back to this page in a `message` event.
 */

const SDK_URL = "https://connect.facebook.net/en_US/sdk.js";
const GRAPH_VERSION = "v21.0";
const FINISH_EVENTS = new Set(["FINISH", "FINISH_ONLY_WABA", "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"]);
/** The ids arrive just before Meta's window closes. This is how long a close waits for them. */
const CLOSE_GRACE_MS = 1500;

export type MetaSignupResult =
  | { readonly kind: "finished"; readonly wabaId: string; readonly phoneNumberId: string }
  | { readonly kind: "cancelled"; readonly step: string }
  | { readonly kind: "error"; readonly message: string };

export type FacebookSdk = {
  init(options: Record<string, unknown>): void;
  login(callback: (response: unknown) => void, options: Record<string, unknown>): void;
};

declare global {
  interface Window {
    FB?: FacebookSdk;
    fbAsyncInit?: () => void;
  }
}

/** The two origins Meta's signup window reports from. Compared whole, so a look-alike host or plain http is refused. */
const META_ORIGIN = "https://www.facebook.com";
const META_ORIGIN_WEB = "https://web.facebook.com";

function fromFacebook(origin: string): boolean {
  return origin === META_ORIGIN || origin === META_ORIGIN_WEB;
}

/** Null for anything that is not a signup report from facebook.com. */
export function parseSignupMessage(origin: string, raw: unknown): MetaSignupResult | null {
  if (!fromFacebook(origin)) return null;
  let payload: unknown = raw;
  if (typeof raw === "string") {
    try {
      payload = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!payload || typeof payload !== "object") return null;
  const { type, event, data } = payload as { type?: unknown; event?: unknown; data?: Record<string, unknown> };
  if (type !== "WA_EMBEDDED_SIGNUP") return null;
  const detail = data ?? {};
  if (typeof event === "string" && FINISH_EVENTS.has(event)) {
    const wabaId = String(detail.waba_id ?? "");
    const phoneNumberId = String(detail.phone_number_id ?? "");
    if (wabaId && phoneNumberId) return { kind: "finished", wabaId, phoneNumberId };
    return { kind: "error", message: "Meta finished without a phone number. Nothing was connected." };
  }
  if (detail.error_message) return { kind: "error", message: String(detail.error_message) };
  if (event === "CANCEL") return { kind: "cancelled", step: String(detail.current_step ?? "") };
  return null;
}

let sdkLoad: { appId: string; promise: Promise<FacebookSdk> } | null = null;

/** Loads the SDK once per app id. Call it before the click: a popup opened after an await is blocked. */
export function loadFacebookSdk(appId: string): Promise<FacebookSdk> {
  if (sdkLoad?.appId === appId) return sdkLoad.promise;
  const options = { appId, autoLogAppEvents: false, xfbml: false, version: GRAPH_VERSION };
  const promise = new Promise<FacebookSdk>((resolve, reject) => {
    if (window.FB) {
      window.FB.init(options);
      resolve(window.FB);
      return;
    }
    window.fbAsyncInit = () => {
      if (!window.FB) {
        reject(new Error("The Facebook SDK loaded without its login function."));
        return;
      }
      window.FB.init(options);
      resolve(window.FB);
    };
    const script = document.createElement("script");
    script.src = SDK_URL;
    script.async = true;
    script.crossOrigin = "anonymous";
    script.onerror = () => {
      sdkLoad = null;
      reject(new Error("The Facebook SDK did not load. Check the network and any content blocker."));
    };
    document.head.appendChild(script);
  });
  sdkLoad = { appId, promise };
  return promise;
}

/** Opens Meta's window. Must run inside the click handler. */
export function startWhatsAppSignup(sdk: FacebookSdk, configId: string): Promise<MetaSignupResult> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result: MetaSignupResult) => {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMessage);
      resolve(result);
    };
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== META_ORIGIN && event.origin !== META_ORIGIN_WEB) return;
      const result = parseSignupMessage(event.origin, event.data);
      if (result) finish(result);
    };
    window.addEventListener("message", onMessage);
    sdk.login(
      () => {
        window.setTimeout(() => finish({ kind: "cancelled", step: "" }), CLOSE_GRACE_MS);
      },
      {
        config_id: configId,
        response_type: "code",
        override_default_response_type: true,
        extras: { setup: {}, featureType: "whatsapp_business_app_onboarding", sessionInfoVersion: "3" },
      },
    );
  });
}

export function resetFacebookSdkForTests(): void {
  sdkLoad = null;
}
