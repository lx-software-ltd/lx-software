import { describe, expect, it } from 'vitest'
import {
  MAX_PARAM_LENGTH,
  SITE_EVENT_NAMES,
  SITE_EVENT_PARAMS,
  pushSiteEvent,
  trackEvent,
} from './analytics'
import { installGtm, type GtmDocument, type GtmWindow } from './gtm'

function fakeDocument(): GtmDocument {
  return {
    head: { appendChild: (node) => node },
    querySelector: () => null,
    createElement: () => ({ async: false, src: '' }),
  }
}

describe('pushSiteEvent', () => {
  it('queues nothing when Tag Manager was never installed', () => {
    const win: GtmWindow = {}
    expect(pushSiteEvent(win, { event: 'nav_click', section: 'projects' })).toBe(false)
    expect(win.dataLayer).toBeUndefined()
  })

  it('queues nothing when the visitor declined analytics', () => {
    const win: GtmWindow = { navigator: { globalPrivacyControl: true } }
    expect(installGtm('GTM-ABC123', win, fakeDocument())).toBe(false)
    expect(pushSiteEvent(win, { event: 'page_not_found', path: '/x' })).toBe(false)
    expect(win.dataLayer).toBeUndefined()
  })

  it('pushes the event after the container loaded', () => {
    const win: GtmWindow = { navigator: {} }
    expect(installGtm('GTM-ABC123', win, fakeDocument())).toBe(true)
    expect(
      pushSiteEvent(win, { event: 'contact_click', channel: 'email', destination: 'mailto:a@b' }),
    ).toBe(true)
    expect(win.dataLayer).toHaveLength(2)
    expect(win.dataLayer?.[1]).toEqual({
      event: 'contact_click',
      channel: 'email',
      destination: 'mailto:a@b',
    })
  })

  it('caps string parameters at the GA4 limit', () => {
    const win: GtmWindow = { dataLayer: [] }
    const question = 'q'.repeat(MAX_PARAM_LENGTH + 40)
    pushSiteEvent(win, { event: 'faq_toggle', question, state: 'open' })
    expect((win.dataLayer?.[0].question as string).length).toBe(MAX_PARAM_LENGTH)
    expect(win.dataLayer?.[0].state).toBe('open')
  })
})

describe('trackEvent', () => {
  it('is a no-op without a window', () => {
    expect(typeof window).toBe('undefined')
    expect(trackEvent({ event: 'media_error', source: 'x.mp4' })).toBe(false)
  })
})

describe('event catalogue', () => {
  it('uses GA4-safe names', () => {
    for (const name of SITE_EVENT_NAMES) expect(name).toMatch(/^[a-z][a-z0-9_]{0,39}$/)
    for (const name of SITE_EVENT_PARAMS) expect(name).toMatch(/^[a-z][a-z0-9_]{0,39}$/)
  })

  it('has no duplicates', () => {
    expect(new Set(SITE_EVENT_NAMES).size).toBe(SITE_EVENT_NAMES.length)
    expect(new Set(SITE_EVENT_PARAMS).size).toBe(SITE_EVENT_PARAMS.length)
  })
})
