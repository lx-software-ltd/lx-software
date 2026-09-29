import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useReducedMotion } from '../lib/motion'
import { pageSections } from '../lib/sections'
import { useActiveSection } from '../lib/useActiveSection'
import { Logo } from './Logo'

export function TopNav() {
  const location = useLocation()
  const reduced = useReducedMotion()
  const onHome = location.pathname === '/'
  const active = useActiveSection(onHome)
  const routeKey = `${location.pathname}${location.hash}`
  const [menuRoute, setMenuRoute] = useState(routeKey)
  const [open, setOpen] = useState(false)
  if (menuRoute !== routeKey) {
    setMenuRoute(routeKey)
    setOpen(false)
  }

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <header className="top-nav">
      <Logo />
      <button
        type="button"
        className="nav-toggle"
        aria-expanded={open}
        aria-controls="primary-nav"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? '[ close ]' : '[ menu ]'}
      </button>
      <nav id="primary-nav" aria-label="Primary">
        <ul className={`nav-links${open ? ' is-open' : ''}`}>
          {pageSections.map((section) => (
            <li key={section.id}>
              <Link
                to={`/#${section.id}`}
                aria-current={onHome && active === section.id ? 'true' : undefined}
                onClick={(event) => {
                  if (!onHome) return
                  const target = document.getElementById(section.id)
                  if (!target) return
                  event.preventDefault()
                  target.scrollIntoView({
                    behavior: reduced ? 'auto' : 'smooth',
                    block: 'start',
                  })
                  history.pushState(null, '', `#${section.id}`)
                  setOpen(false)
                }}
              >
                {section.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  )
}
