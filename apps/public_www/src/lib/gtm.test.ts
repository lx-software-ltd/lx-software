import { describe, expect, it } from 'vitest'
import {
  analyticsDeclined,
  gtmContainerId,
  gtmScriptUrl,
  installGtm,
  type GtmDocument,
  type GtmScriptElement,
  type GtmWindow,
} from './gtm'

function fakeDocument(existing: string[] = []) {
  const appended: GtmScriptElement[] = []
  const doc: GtmDocument = {
    head: {
      appendChild(node) {
        appended.push(node)
        return node
      },
    },
    querySelector() {
      return existing.length ? {} : null
    },
    createElement() {
      return { async: false, src: '' }
    },
  }
  return { doc, appended }
}

describe('gtmContainerId', () => {
  it('accepts a GTM container id and upper-cases it', () => {
    expect(gtmContainerId('GTM-ABC123')).toBe('GTM-ABC123')
    expect(gtmContainerId(' gtm-abc123 ')).toBe('GTM-ABC123')
  })

  it('rejects empty, measurement ids and injection attempts', () => {
    expect(gtmContainerId(undefined)).toBe('')
    expect(gtmContainerId('')).toBe('')
    expect(gtmContainerId('G-ABC123')).toBe('')
    expect(gtmContainerId('GTM-ABC"><script>')).toBe('')
    expect(gtmContainerId('GTM-')).toBe('')
  })
})

describe('gtmScriptUrl', () => {
  it('points at gtm.js on googletagmanager.com', () => {
    expect(gtmScriptUrl('GTM-ABC123')).toBe(
      'https://www.googletagmanager.com/gtm.js?id=GTM-ABC123',
    )
  })
})

describe('analyticsDeclined', () => {
  it('honours Global Privacy Control and Do Not Track', () => {
    expect(analyticsDeclined(undefined)).toBe(false)
    expect(analyticsDeclined({})).toBe(false)
    expect(analyticsDeclined({ doNotTrack: '0' })).toBe(false)
    expect(analyticsDeclined({ doNotTrack: 'unspecified' })).toBe(false)
    expect(analyticsDeclined({ doNotTrack: '1' })).toBe(true)
    expect(analyticsDeclined({ doNotTrack: 'yes' })).toBe(true)
    expect(analyticsDeclined({ globalPrivacyControl: true })).toBe(true)
  })
})

describe('installGtm', () => {
  it('pushes gtm.start and appends the async script', () => {
    const win: GtmWindow = {}
    const { doc, appended } = fakeDocument()
    expect(installGtm('GTM-ABC123', win, doc)).toBe(true)
    expect(appended).toHaveLength(1)
    expect(appended[0]).toEqual({
      async: true,
      src: 'https://www.googletagmanager.com/gtm.js?id=GTM-ABC123',
    })
    expect(win.dataLayer).toHaveLength(1)
    expect(win.dataLayer?.[0]).toMatchObject({ event: 'gtm.js' })
    expect(typeof win.dataLayer?.[0]['gtm.start']).toBe('number')
  })

  it('keeps an existing dataLayer', () => {
    const seed = { event: 'seed' }
    const win: GtmWindow = { dataLayer: [seed] }
    const { doc } = fakeDocument()
    installGtm('GTM-ABC123', win, doc)
    expect(win.dataLayer?.[0]).toBe(seed)
    expect(win.dataLayer).toHaveLength(2)
  })

  it('does nothing without a container id', () => {
    const win: GtmWindow = {}
    const { doc, appended } = fakeDocument()
    expect(installGtm('', win, doc)).toBe(false)
    expect(installGtm('G-ABC123', win, doc)).toBe(false)
    expect(appended).toHaveLength(0)
    expect(win.dataLayer).toBeUndefined()
  })

  it('does nothing when the visitor opted out', () => {
    const win: GtmWindow = { navigator: { globalPrivacyControl: true } }
    const { doc, appended } = fakeDocument()
    expect(installGtm('GTM-ABC123', win, doc)).toBe(false)
    expect(appended).toHaveLength(0)
    expect(win.dataLayer).toBeUndefined()
  })

  it('does not load the container twice', () => {
    const win: GtmWindow = {}
    const { doc, appended } = fakeDocument(['gtm'])
    expect(installGtm('GTM-ABC123', win, doc)).toBe(false)
    expect(appended).toHaveLength(0)
  })
})
