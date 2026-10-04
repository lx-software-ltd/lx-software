import { Link } from 'react-router-dom'
import { trackEvent } from '../lib/analytics'
import { defaultSiteContent } from '../lib/content'

/** Closing block of a content page: one line of copy and one link to the contact section. */
export function CallToAction({ page }: { page: string }) {
  const { cta } = defaultSiteContent
  return (
    <aside className="cta" aria-labelledby="cta-heading">
      <h2 id="cta-heading">{cta.heading}</h2>
      <p>{cta.body}</p>
      <Link to={cta.href} className="cta-link" onClick={() => trackEvent({ event: 'cta_click', page })}>
        {cta.label}
      </Link>
    </aside>
  )
}
