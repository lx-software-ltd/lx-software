export interface ContactLink {
  id: 'tel' | 'email' | 'whatsapp' | 'wechat'
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
    (import.meta.env.VITE_CONTACT_EMAIL ?? '').trim() || 'hello@lx-software.com'
  const whatsapp = (import.meta.env.VITE_CONTACT_WHATSAPP ?? '').replace(/\D/g, '')
  const wechatId = (import.meta.env.VITE_CONTACT_WECHAT_ID ?? '').trim()

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
  ]
}

export function wechatId(): string {
  return (import.meta.env.VITE_CONTACT_WECHAT_ID ?? '').trim()
}
