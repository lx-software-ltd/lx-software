import { Link } from 'react-router-dom'
import { defaultSiteContent } from '../lib/content'

export function BottomBar() {
  const { name, owner } = defaultSiteContent.site
  return (
    <footer className="bottom-bar">
      <div className="container bottom-bar-inner">
        <p>
          © {new Date().getFullYear()} {owner ? `${owner} · ${name}` : name}
        </p>
        <nav aria-label="Legal">
          <Link to="/privacy">Privacy Policy</Link>
          <Link to="/terms">Terms &amp; Conditions</Link>
        </nav>
      </div>
    </footer>
  )
}
