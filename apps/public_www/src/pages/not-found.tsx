import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { trackEvent } from '../lib/analytics'
import { defaultSiteContent } from '../lib/content'
import { usePageMeta } from '../lib/seo'

export function NotFoundPage() {
  const { pathname } = useLocation()
  const { chrome, site } = defaultSiteContent
  usePageMeta(
    `${chrome.notFoundTitle} — ${site.name}`,
    '/404',
    chrome.notFoundDescription,
    'noindex',
  )

  useEffect(() => {
    trackEvent({ event: 'page_not_found', path: pathname })
  }, [pathname])

  return (
    <section className="section legal container">
      <h1>{chrome.notFoundTitle}</h1>
      <p>{chrome.notFoundBody}</p>
      <Link to="/">{chrome.notFoundBack}</Link>
    </section>
  )
}
