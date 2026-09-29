import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useReducedMotion } from '../lib/motion'
import { pageSections } from '../lib/sections'
import { useActiveSection } from '../lib/useActiveSection'

const mobileNav = '(max-width: 760px)'

export function TopNav() {
  const location = useLocation()
  const navigate = useNavigate()
  const reduced = useReducedMotion()
  const onHome = location.pathname === '/'
  const active = useActiveSection(onHome)
  const routeKey = `${location.pathname}${location.hash}`
  const [menuRoute, setMenuRoute] = useState(routeKey)
  const [open, setOpen] = useState(false)
  const toggleRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLUListElement>(null)
  if (menuRoute !== routeKey) {
    setMenuRoute(routeKey)
    setOpen(false)
  }

  useEffect(() => {
    if (!open || !window.matchMedia(mobileNav).matches) return
    const menu = menuRef.current
    const links = menu ? [...menu.querySelectorAll<HTMLAnchorElement>('a')] : []
    links[0]?.focus()

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        toggleRef.current?.focus()
        return
      }
      if (event.key !== 'Tab' || links.length === 0) return
      const first = links[0]
      const last = links[links.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      if (menu?.contains(target) || toggleRef.current?.contains(target)) return
      setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('pointerdown', onPointerDown)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open])

  return (
    <header className="top-nav">
      <button
        ref={toggleRef}
        type="button"
        className="nav-toggle"
        aria-expanded={open}
        aria-controls="primary-nav"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? '[ close ]' : '[ menu ]'}
      </button>
      <nav id="primary-nav" aria-label="Primary">
        <ul ref={menuRef} className={`nav-links${open ? ' is-open' : ''}`}>
          {pageSections.map((section) => (
            <li key={section.id}>
              <Link
                to={`/#${section.id}`}
                aria-current={onHome && active === section.id ? 'true' : undefined}
                onClick={(event) => {
                  setOpen(false)
                  if (!onHome) return
                  event.preventDefault()
                  const hash = `#${section.id}`
                  if (location.hash !== hash) navigate(`/${hash}`)
                  document.getElementById(section.id)?.scrollIntoView({
                    behavior: reduced ? 'auto' : 'smooth',
                    block: 'start',
                  })
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
