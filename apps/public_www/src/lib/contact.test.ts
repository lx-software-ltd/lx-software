import { afterEach, describe, expect, it, vi } from 'vitest'
import { contactLinks } from './contact'

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('contactLinks', () => {
  it('uses the product mailbox and leaves telephone and WhatsApp unset', () => {
    const links = Object.fromEntries(contactLinks().map((item) => [item.id, item]))
    expect(links.email?.href).toBe('mailto:hello@lx-software.com')
    expect(links.tel?.href).toBeNull()
    expect(links.tel?.accessibleName).toBe('Telephone not configured')
    expect(links.whatsapp?.href).toBeNull()
    expect(links.wechat?.href).toBe('/wechat')
  })

  it('builds tel and WhatsApp links from the public env', () => {
    vi.stubEnv('VITE_CONTACT_TEL', '+15555550100')
    vi.stubEnv('VITE_CONTACT_WHATSAPP', '+1 (555) 555-0100')
    vi.stubEnv('VITE_CONTACT_EMAIL', 'board@example.com')
    const links = Object.fromEntries(contactLinks().map((item) => [item.id, item]))
    expect(links.tel?.href).toBe('tel:+15555550100')
    expect(links.whatsapp?.href).toBe('https://wa.me/15555550100')
    expect(links.email?.href).toBe('mailto:board@example.com')
  })
})
