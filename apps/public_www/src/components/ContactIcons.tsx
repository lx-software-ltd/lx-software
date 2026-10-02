import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { trackEvent } from '../lib/analytics'
import { contactDestination, contactLinks, type ContactLink as ContactChannel } from '../lib/contact'
import { defaultSiteContent } from '../lib/content'
import { EmailIcon, LinkedInIcon, TelephoneIcon, WeChatIcon, WhatsAppIcon } from './icons'

function Icon({ id }: { id: ContactChannel['id'] }) {
  if (id === 'whatsapp') return <WhatsAppIcon />
  if (id === 'wechat') return <WeChatIcon />
  if (id === 'linkedin') return <LinkedInIcon />
  if (id === 'tel') return <TelephoneIcon />
  return <EmailIcon />
}

function ContactLink({ item, children }: { item: ContactChannel; children: ReactNode }) {
  if (!item.href) {
    return (
      <div className="contact-unavailable">
        {children}
        <span className="contact-note">{defaultSiteContent.chrome.notConfigured}</span>
      </div>
    )
  }
  const record = () =>
    trackEvent({
      event: 'contact_click',
      channel: item.id,
      destination: contactDestination(item.href),
    })
  if (item.href.startsWith('/')) {
    return (
      <Link to={item.href} aria-label={item.accessibleName} onClick={record}>
        {children}
      </Link>
    )
  }
  return (
    <a
      href={item.href}
      aria-label={item.accessibleName}
      onClick={record}
      {...(item.external ? { target: '_blank', rel: 'noreferrer' } : {})}
    >
      {children}
    </a>
  )
}

export function ContactIcons() {
  return (
    <ul className="contact-list">
      {contactLinks().map((item) => (
        <li key={item.id}>
          <ContactLink item={item}>
            <Icon id={item.id} />
            <span>[ {item.label.toUpperCase()} ]</span>
          </ContactLink>
        </li>
      ))}
    </ul>
  )
}
