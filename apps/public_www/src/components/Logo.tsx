import { Link, useLocation } from 'react-router-dom'
import { useReducedMotion } from '../lib/motion'

export function Logo() {
  const location = useLocation()
  const reduced = useReducedMotion()

  return (
    <Link
      to="/"
      className="logo"
      aria-label="LX Software, back to top"
      onClick={(event) => {
        if (location.pathname !== '/') return
        event.preventDefault()
        window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' })
        history.replaceState(null, '', '/')
      }}
    >
      <svg width="60" height="60" viewBox="0 0 60 60" aria-hidden="true">
        <rect x="1" y="1" width="58" height="58" rx="14" fill="#000" stroke="#444" />
        <text
          x="30"
          y="31"
          textAnchor="middle"
          dominantBaseline="middle"
          fill="#fff"
          fontFamily="IBM Plex Mono, ui-monospace, monospace"
          fontSize="20"
          fontWeight="700"
        >
          LX
        </text>
      </svg>
    </Link>
  )
}
