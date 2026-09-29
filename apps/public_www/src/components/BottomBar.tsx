import { Link } from 'react-router-dom'

export function BottomBar() {
  return (
    <footer className="bottom-bar">
      <div className="container bottom-bar-inner">
        <p>© {new Date().getFullYear()} LX Software</p>
        <nav aria-label="Legal">
          <Link to="/privacy">Privacy Policy</Link>
          <Link to="/terms">Terms &amp; Conditions</Link>
        </nav>
      </div>
    </footer>
  )
}
