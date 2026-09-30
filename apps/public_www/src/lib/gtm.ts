/**
 * Google Tag Manager loader. The container id comes from `VITE_GTM_ID` at
 * build time; an empty or malformed value leaves the page without any Google
 * script. GA4 is configured inside the container, not in this repository.
 *
 * The CloudFront CSP (`backend/infrastructure/lib/public-website-stack.ts`)
 * only allows the Google Tag Manager and Google Analytics hosts, so the
 * container must not use Custom HTML tags (inline scripts are blocked).
 */

export const GTM_SCRIPT_ORIGIN = 'https://www.googletagmanager.com'

export function gtmContainerId(raw: string | undefined): string {
  const value = (raw ?? '').trim().toUpperCase()
  return /^GTM-[A-Z0-9]{4,12}$/.test(value) ? value : ''
}

export function gtmScriptUrl(id: string): string {
  return `${GTM_SCRIPT_ORIGIN}/gtm.js?id=${encodeURIComponent(id)}`
}

export interface PrivacySignals {
  doNotTrack?: string | null
  globalPrivacyControl?: boolean
}

/**
 * Global Privacy Control and Do Not Track are honoured: when either is set
 * the analytics script is never requested. The privacy policy says so.
 */
export function analyticsDeclined(signals: PrivacySignals | undefined): boolean {
  if (!signals) return false
  if (signals.globalPrivacyControl === true) return true
  return signals.doNotTrack === '1' || signals.doNotTrack === 'yes'
}

export interface GtmScriptElement {
  async: boolean
  src: string
}

export interface GtmDocument<S extends GtmScriptElement = GtmScriptElement> {
  head: { appendChild(node: S): unknown }
  querySelector(selector: string): unknown
  createElement(tag: 'script'): S
}

export interface GtmWindow {
  dataLayer?: Record<string, unknown>[]
  navigator?: PrivacySignals
}

/**
 * Pushes `gtm.start` onto `dataLayer` and appends the async `gtm.js` script,
 * the same steps as the snippet Google shows in the container UI. Returns
 * true when the script was added.
 */
export function installGtm<S extends GtmScriptElement>(
  rawId: string | undefined,
  win: GtmWindow,
  doc: GtmDocument<S>,
): boolean {
  const id = gtmContainerId(rawId)
  if (!id) return false
  if (analyticsDeclined(win.navigator)) return false
  if (doc.querySelector(`script[src^="${GTM_SCRIPT_ORIGIN}/gtm.js"]`)) return false
  const layer = win.dataLayer ?? []
  win.dataLayer = layer
  layer.push({ 'gtm.start': Date.now(), event: 'gtm.js' })
  const script = doc.createElement('script')
  script.async = true
  script.src = gtmScriptUrl(id)
  doc.head.appendChild(script)
  return true
}
