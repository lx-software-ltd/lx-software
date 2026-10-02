import { defaultSiteContent } from './content'
import { linkedinUrl } from './linkedin'

export interface ContactLink {
  id: 'tel' | 'email' | 'whatsapp' | 'wechat' | 'linkedin'
  label: string
  accessibleName: string
  href: string | null
  external: boolean
}

function wechatHref(id: string): string {
  if (
    id &&
    typeof navigator !== 'undefined' &&
    /MicroMessenger|WeChat/i.test(navigator.userAgent)
  ) {
    return `weixin://dl/chat?${encodeURIComponent(id)}`
  }
  return '/wechat'
}

export function contactLinks(): ContactLink[] {
  const tel = (import.meta.env.VITE_CONTACT_TEL ?? '').trim()
  const email =
    (import.meta.env.VITE_CONTACT_EMAIL ?? '').trim() || defaultSiteContent.site.email
  const whatsapp = (import.meta.env.VITE_CONTACT_WHATSAPP ?? '').replace(/\D/g, '')
  const wechatId = (import.meta.env.VITE_CONTACT_WECHAT_ID ?? '').trim()
  const linkedin = linkedinUrl(import.meta.env.VITE_CONTACT_LINKEDIN)

  return [
    {
      id: 'tel',
      label: 'Tel',
      accessibleName: tel ? `Telephone ${tel}` : 'Telephone not configured',
      href: tel ? `tel:${tel}` : null,
      external: false,
    },
    {
      id: 'email',
      label: 'Email',
      accessibleName: `Email ${email}`,
      href: `mailto:${email}`,
      external: false,
    },
    {
      id: 'whatsapp',
      label: 'WhatsApp',
      accessibleName: whatsapp ? 'WhatsApp' : 'WhatsApp not configured',
      href: whatsapp ? `https://wa.me/${whatsapp}` : null,
      external: true,
    },
    {
      id: 'wechat',
      label: 'WeChat',
      accessibleName: 'WeChat',
      href: wechatHref(wechatId),
      external: false,
    },
    {
      id: 'linkedin',
      label: 'LinkedIn',
      accessibleName: linkedin ? 'LinkedIn profile' : 'LinkedIn not configured',
      href: linkedin || null,
      external: true,
    },
  ]
}

/**
 * What a contact click points at, without the number or address itself:
 * the scheme for `tel:` / `mailto:` / `weixin:`, the host for http(s), the
 * path for an in-site route. This is what the analytics event records.
 */
export function contactDestination(href: string | null): string {
  if (!href) return 'unavailable'
  if (href.startsWith('/')) return href
  const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(href)?.[1]?.toLowerCase()
  if (scheme === 'http' || scheme === 'https') {
    try {
      return new URL(href).hostname
    } catch {
      return scheme
    }
  }
  return scheme ?? 'unknown'
}

export function wechatId(): string {
  return (import.meta.env.VITE_CONTACT_WECHAT_ID ?? '').trim()
}
