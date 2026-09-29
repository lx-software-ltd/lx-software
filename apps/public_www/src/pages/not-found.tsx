import { Link } from 'react-router-dom'
import { usePageMeta } from '../lib/seo'

export function NotFoundPage() {
  usePageMeta(
    'Page not found — LX Software',
    '/404',
    'That page is not on the LX Software site.',
  )

  return (
    <section className="section legal container">
      <h1>Page not found</h1>
      <p>That address is not on this site.</p>
      <Link to="/">[ back to the top ]</Link>
    </section>
  )
}
