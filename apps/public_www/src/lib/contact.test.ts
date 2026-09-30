import { afterEach, describe, expect, it, vi } from 'vitest'
import { contactDestination, contactLinks } from './contact'

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
    expect(links.linkedin?.href).toBeNull()
    expect(links.linkedin?.accessibleName).toBe('LinkedIn not configured')
    expect(contactLinks().map((item) => item.id)).toEqual([
      'tel',
      'email',
      'whatsapp',
      'wechat',
      'linkedin',
    ])
  })

  it('links LinkedIn from the public env', () => {
    vi.stubEnv('VITE_CONTACT_LINKEDIN', 'https://www.linkedin.com/in/sample-owner/')
    const links = Object.fromEntries(contactLinks().map((item) => [item.id, item]))
    expect(links.linkedin?.href).toBe('https://www.linkedin.com/in/sample-owner')
    expect(links.linkedin?.external).toBe(true)
    expect(links.linkedin?.accessibleName).toBe('LinkedIn profile')
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

describe('contactDestination', () => {
  it('keeps the scheme or host and drops the number or address', () => {
    expect(contactDestination('tel:+15555550100')).toBe('tel')
    expect(contactDestination('mailto:board@example.com')).toBe('mailto')
    expect(contactDestination('https://wa.me/15555550100')).toBe('wa.me')
    expect(contactDestination('https://www.linkedin.com/in/sample-owner')).toBe('www.linkedin.com')
    expect(contactDestination('weixin://dl/chat?sample')).toBe('weixin')
    expect(contactDestination('/wechat')).toBe('/wechat')
    expect(contactDestination(null)).toBe('unavailable')
  })
})
