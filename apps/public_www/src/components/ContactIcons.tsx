import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { contactLinks, type ContactLink } from '../lib/contact'

function Icon({ id }: { id: ContactLink['id'] }) {
  const common = {
    viewBox: '0 0 48 48',
    'aria-hidden': true as const,
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.6,
  }
  if (id === 'tel') {
    return (
      <svg {...common}>
        <path d="M16 10h6l2 6-4 2a16 16 0 0 0 8 8l2-4 6 2v6c0 2-2 4-4 4C20 34 14 20 14 14c0-2 0-4 2-4z" />
      </svg>
    )
  }
  if (id === 'email') {
    return (
      <svg {...common}>
        <rect x="8" y="12" width="32" height="24" />
        <path d="M8 14l16 12L40 14" />
      </svg>
    )
  }
  if (id === 'whatsapp') {
    return (
      <svg {...common}>
        <path d="M14 34l-2 6 6-2a16 16 0 1 0-4-4z" />
        <path d="M20 20c2 6 6 8 8 8" />
      </svg>
    )
  }
  return (
    <svg {...common}>
      <circle cx="18" cy="22" r="8" />
      <circle cx="30" cy="26" r="8" />
    </svg>
  )
}

function Shell({ item, children }: { item: ContactLink; children: ReactNode }) {
  if (!item.href) {
    return (
      <div className="contact-unavailable">
        {children}
        <span className="contact-note">Not configured</span>
      </div>
    )
  }
  if (item.href.startsWith('/')) {
    return (
      <Link to={item.href} aria-label={item.accessibleName}>
        {children}
      </Link>
    )
  }
  return (
    <a
      href={item.href}
      aria-label={item.accessibleName}
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
          <Shell item={item}>
            <Icon id={item.id} />
            <span>[ {item.label.toUpperCase()} ]</span>
          </Shell>
        </li>
      ))}
    </ul>
  )
}
