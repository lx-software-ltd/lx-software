import type { GtmWindow } from './gtm'

/**
 * Site events pushed onto `dataLayer` for Google Tag Manager. The container
 * forwards each one to GA4 as an event of the same name (one GA4 Event tag
 * on a Custom Event trigger; `scripts/configure-public-analytics.py` keeps
 * that tag, its trigger and the parameter variables in step with this list).
 *
 * Enhanced measurement already records `page_view` (including React Router
 * navigation), `scroll`, `click` on outbound http(s) links, `file_download`
 * and `video_*`. These names cover what it cannot see: `tel:` / `mailto:`
 * links, in-page routes, disclosure widgets, carousel buttons, section
 * navigation, 404 hits and a harbour video that failed to load.
 */
export type SiteEvent =
  | { event: 'contact_click'; channel: 'tel' | 'email' | 'whatsapp' | 'wechat' | 'linkedin'; destination: string }
  | { event: 'faq_toggle'; question: string; state: 'open' | 'closed' }
  | { event: 'project_open'; project: string; destination: string }
  | { event: 'project_navigate'; direction: 'next' | 'prev'; method: 'button' | 'keyboard' }
  | { event: 'nav_click'; section: string }
  | { event: 'page_not_found'; path: string }
  | { event: 'media_error'; source: string }

export type SiteEventName = SiteEvent['event']

export const SITE_EVENT_NAMES = [
  'contact_click',
  'faq_toggle',
  'project_open',
  'project_navigate',
  'nav_click',
  'page_not_found',
  'media_error',
] as const satisfies readonly SiteEventName[]

export const SITE_EVENT_PARAMS = [
  'channel',
  'destination',
  'question',
  'state',
  'project',
  'direction',
  'method',
  'section',
  'path',
  'source',
] as const

type KeysOf<T> = T extends unknown ? keyof T : never
type ParamKey = Exclude<KeysOf<SiteEvent>, 'event'>
type UnlistedParam = Exclude<ParamKey, (typeof SITE_EVENT_PARAMS)[number]>
type UnknownParam = Exclude<(typeof SITE_EVENT_PARAMS)[number], ParamKey>

/** Fails to compile when SITE_EVENT_PARAMS and SiteEvent drift apart. */
export const siteEventParamsInSync: [UnlistedParam | UnknownParam] extends [never]
  ? true
  : UnlistedParam | UnknownParam = true

/** GA4 truncates event parameter values at 100 characters. */
export const MAX_PARAM_LENGTH = 100

/**
 * Pushes one event when Tag Manager was installed. `installGtm` only creates
 * `dataLayer` after the container id, Global Privacy Control and Do Not
 * Track checks pass, so a missing array means nothing may be recorded.
 * Returns true when the event was queued.
 */
export function pushSiteEvent(win: GtmWindow, event: SiteEvent): boolean {
  const layer = win.dataLayer
  if (!layer) return false
  const trimmed: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(event)) {
    trimmed[key] = typeof value === 'string' ? value.slice(0, MAX_PARAM_LENGTH) : value
  }
  layer.push(trimmed)
  return true
}

export function trackEvent(event: SiteEvent): boolean {
  if (typeof window === 'undefined') return false
  return pushSiteEvent(window as GtmWindow, event)
}
