import { Link } from 'react-router-dom'
import { defaultSiteContent } from '../lib/content'

export function BottomBar() {
  const content = defaultSiteContent
  const { name, owner } = content.site
  return (
    <footer className="bottom-bar">
      <div className="container bottom-bar-inner">
        <nav aria-label={content.chrome.pagesLabel} className="bottom-bar-pages">
          {content.pages.map((page) => (
            <Link key={page.slug} to={`/${page.slug}`}>
              {page.navLabel}
            </Link>
          ))}
        </nav>
        <p>
          © {new Date().getFullYear()} {owner ? `${owner} · ${name}` : name}
        </p>
        <nav aria-label="Legal">
          <Link to="/privacy">{content.legal.privacy.title}</Link>
          <Link to="/terms">{content.legal.terms.title}</Link>
        </nav>
      </div>
    </footer>
  )
}
