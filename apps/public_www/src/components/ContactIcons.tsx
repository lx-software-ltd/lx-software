import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { trackEvent } from '../lib/analytics'
import { contactDestination, contactLinks, type ContactLink } from '../lib/contact'

function Icon({ id }: { id: ContactLink['id'] }) {
  if (id === 'whatsapp') return <WhatsAppIcon />
  if (id === 'wechat') return <WeChatIcon />
  if (id === 'linkedin') return <LinkedInIcon />
  if (id === 'tel') return <TelephoneIcon />
  return <EmailIcon />
}

function TelephoneIcon() {
  return (
    <svg viewBox="0 0 48 48" width="48" height="48" aria-hidden="true">
      <rect width="48" height="48" rx="11" fill="#34C759" />
      <path
        fill="#fff"
        d="M14.2 20.1c1.7 3.3 4.4 6 7.7 7.7l2.6-2.6c.3-.3.8-.4 1.2-.3 1.3.4 2.7.7 4.2.7.6 0 1.2.5 1.2 1.2v4.1c0 .6-.5 1.2-1.2 1.2-11 0-19.9-8.9-19.9-19.9 0-.6.5-1.2 1.2-1.2h4.1c.6 0 1.2.5 1.2 1.2 0 1.5.2 2.9.7 4.2.1.4 0 .9-.3 1.2l-2.7 2.5z"
      />
    </svg>
  )
}

function EmailIcon() {
  return (
    <svg viewBox="0 0 48 48" width="48" height="48" aria-hidden="true">
      <rect width="48" height="48" rx="11" fill="#0A84FF" />
      <path
        fill="#fff"
        d="M11.5 16.8h25c1.2 0 2.2 1 2.2 2.2v12.2c0 1.2-1 2.2-2.2 2.2h-25c-1.2 0-2.2-1-2.2-2.2V19c0-1.2 1-2.2 2.2-2.2z"
      />
      <path
        fill="none"
        stroke="#0A84FF"
        strokeWidth="2.4"
        strokeLinejoin="round"
        strokeLinecap="round"
        d="M12.2 18.2 24 26.8 35.8 18.2"
      />
    </svg>
  )
}

function WhatsAppIcon() {
  return (
    <svg viewBox="0 0 720 720" width="720" height="720" aria-hidden="true" fill="#25D366">
      <path d="M360,0C161.18,0,0,161.18,0,360c0,65.41,17.45,126.75,47.94,179.61L0,720l187.02-44.21c51.34,28.18,110.28,44.21,172.98,44.21,198.82,0,360-161.18,360-360S558.82,0,360,0ZM360,655.52c-60.17,0-116.13-17.98-162.82-48.87l-110.49,28.14,30.99-105.61c-33.53-47.93-53.2-106.26-53.2-169.19,0-163.21,132.31-295.52,295.52-295.52s295.52,132.31,295.52,295.52-132.31,295.52-295.52,295.52Z" />
      <path d="M444.35,407.52l87.1,41.06c4,1.88,6.56,5.94,6.2,10.34-.94,11.46-5.54,34.43-26.13,55.02-58.12,58.12-162.49-7.64-166.74-10.18-25.67-13.79-50.06-32.24-73.19-55.36-23.12-23.12-41.58-47.52-55.37-73.19-2.55-4.24-68.31-108.61-10.18-166.74,20.59-20.59,43.56-25.19,55.02-26.13,4.41-.36,8.46,2.2,10.34,6.2l41.07,87.1c1.94,4.12,1.09,9.02-2.13,12.24l-30.61,30.61c-6.62,6.62-8.56,16.93-4,25.11,11.17,20.03,26.19,39.32,43.59,57.07,17.75,17.4,37.04,32.43,57.07,43.59,8.18,4.56,18.48,2.62,25.11-4l30.61-30.61c3.22-3.22,8.12-4.08,12.24-2.13Z" />
    </svg>
  )
}

function LinkedInIcon() {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
      <path
        fill="#0A66C2"
        d="M22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"
      />
      <path
        fill="#fff"
        d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452z"
      />
    </svg>
  )
}

function WeChatIcon() {
  return (
    <svg viewBox="0 0 33 27" width="33" height="27" aria-hidden="true" fill="none">
      <path
        d="M7.98557 19.5685C9.15835 19.9072 10.4238 20.0965 11.7342 20.0965C18.0746 20.0965 23.2158 15.7818 23.2158 10.4592C23.2158 5.1365 18.0746 0.821838 11.7316 0.821838C5.38852 0.821838 0.25 5.1365 0.25 10.4592C0.25 13.3632 1.79606 15.9765 4.21838 17.7445C4.41164 17.8832 4.53872 18.1125 4.53872 18.3738C4.53872 18.4592 4.52018 18.5392 4.499 18.6192C4.30575 19.3445 3.99601 20.5098 3.98277 20.5632C3.95894 20.6538 3.92188 20.7498 3.92188 20.8458C3.92188 21.0592 4.09396 21.2325 4.30575 21.2325C4.39046 21.2325 4.45665 21.2005 4.52813 21.1605L7.04311 19.6992C7.23107 19.5898 7.43227 19.5205 7.652 19.5205C7.76849 19.5205 7.88232 19.5392 7.99087 19.5712L7.98557 19.5685Z"
        fill="url(#wechat-bubble-green)"
      />
      <path
        d="M17.0935 7.37416C17.0935 8.22483 16.4079 8.91549 15.5634 8.91549C14.7189 8.91549 14.0332 8.22483 14.0332 7.37416C14.0332 6.52349 14.7189 5.83282 15.5634 5.83282C16.4079 5.83282 17.0935 6.52349 17.0935 7.37416Z"
        fill="#168743"
      />
      <path
        d="M9.43534 7.3741C9.43534 8.22476 8.74968 8.91543 7.90517 8.91543C7.06067 8.91543 6.375 8.22476 6.375 7.3741C6.375 6.52343 7.06067 5.83276 7.90517 5.83276C8.74968 5.83276 9.43534 6.52343 9.43534 7.3741Z"
        fill="#168743"
      />
      <path
        d="M25.573 25.6191C24.5961 25.9017 23.5425 26.0591 22.4491 26.0591C17.165 26.0591 12.8789 22.4617 12.8789 18.0271C12.8789 13.5924 17.1623 9.99506 22.4491 9.99506C27.7359 9.99506 32.0166 13.5924 32.0166 18.0271C32.0166 20.4484 30.7274 22.6271 28.7101 24.0991C28.5486 24.2164 28.4427 24.4057 28.4427 24.6217C28.4427 24.6937 28.4586 24.7577 28.4771 24.8271C28.6386 25.4324 28.8954 26.4004 28.9086 26.4457C28.9298 26.5231 28.9589 26.6004 28.9589 26.6804C28.9589 26.8591 28.816 27.0031 28.6386 27.0031C28.5698 27.0031 28.5142 26.9764 28.4533 26.9417L26.3592 25.7231C26.2004 25.6324 26.0336 25.5737 25.8509 25.5737C25.753 25.5737 25.6577 25.5897 25.5703 25.6164L25.573 25.6191Z"
        fill="url(#wechat-bubble-light)"
      />
      <path
        d="M17.9844 15.4569C17.9844 16.1662 18.5562 16.7422 19.2604 16.7422C19.9646 16.7422 20.5364 16.1662 20.5364 15.4569C20.5364 14.7476 19.9646 14.1716 19.2604 14.1716C18.5562 14.1716 17.9844 14.7476 17.9844 15.4569Z"
        fill="#919191"
      />
      <path
        d="M24.3633 15.457C24.3633 16.1663 24.9351 16.7423 25.6393 16.7423C26.3435 16.7423 26.9153 16.1663 26.9153 15.457C26.9153 14.7476 26.3435 14.1716 25.6393 14.1716C24.9351 14.1716 24.3633 14.7476 24.3633 15.457Z"
        fill="#919191"
      />
      <defs>
        <linearGradient id="wechat-bubble-green" x1="11.7316" y1="21.2298" x2="11.7316" y2="0.821838" gradientUnits="userSpaceOnUse">
          <stop offset="0.06" stopColor="#05CD66" />
          <stop offset="0.22" stopColor="#0DD068" />
          <stop offset="0.48" stopColor="#26DA6F" />
          <stop offset="0.81" stopColor="#4DEB7A" />
          <stop offset="0.95" stopColor="#61F380" />
        </linearGradient>
        <linearGradient id="wechat-bubble-light" x1="22.4517" y1="27.0031" x2="22.4517" y2="9.99506" gradientUnits="userSpaceOnUse">
          <stop offset="0.08" stopColor="#D9D9D9" />
          <stop offset="1" stopColor="#F0F0F0" />
        </linearGradient>
      </defs>
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
          <Shell item={item}>
            <Icon id={item.id} />
            <span>[ {item.label.toUpperCase()} ]</span>
          </Shell>
        </li>
      ))}
    </ul>
  )
}
