import { useEffect } from 'react'
import { Outlet, useLocation, useNavigationType } from 'react-router-dom'
import { defaultSiteContent } from '../lib/content'
import { useReducedMotion } from '../lib/motion'
import { BackgroundVideo } from './BackgroundVideo'
import { BottomBar } from './BottomBar'
import { CinemaLayer } from './CinemaLayer'
import { MotionProvider } from './MotionProvider'
import { ScrollProgress } from './ScrollProgress'
import { TopNav } from './TopNav'

function Shell() {
  const location = useLocation()
  const navigationType = useNavigationType()
  const reduced = useReducedMotion()
  const still = reduced || location.pathname !== '/'

  // A link clicked mid-page (service card → service page) opens the new
  // route at the top with focus on its content; the home page keeps its own
  // hash scrolling, and Back/Forward keep the browser's scroll restoration.
  useEffect(() => {
    if (location.pathname === '/' || navigationType !== 'PUSH') return
    window.scrollTo({ top: 0, behavior: 'auto' })
    document.getElementById('content')?.focus({ preventScroll: true })
  }, [location.pathname, navigationType])

  return (
    <div className={`site-shell${still ? ' is-still' : ''}`}>
      <a className="skip-link" href="#content">
        {defaultSiteContent.chrome.skipToContent}
      </a>
      <ScrollProgress />
      <BackgroundVideo still={still} />
      <CinemaLayer />
      <TopNav />
      <main id="content" tabIndex={-1} className="site-main">
        <Outlet />
      </main>
      <BottomBar />
    </div>
  )
}

export function SiteLayout() {
  return (
    <MotionProvider>
      <Shell />
    </MotionProvider>
  )
}
