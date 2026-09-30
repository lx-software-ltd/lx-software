import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { trackEvent } from '../lib/analytics'
import { usePageMeta } from '../lib/seo'

export function NotFoundPage() {
  const { pathname } = useLocation()
  usePageMeta(
    'Page not found — LX Software',
    '/404',
    'That page is not on the LX Software site.',
  )

  useEffect(() => {
    trackEvent({ event: 'page_not_found', path: pathname })
  }, [pathname])

  return (
    <section className="section legal container">
      <h1>Page not found</h1>
      <p>That address is not on this site.</p>
      <Link to="/">[ back to the top ]</Link>
    </section>
  )
}
