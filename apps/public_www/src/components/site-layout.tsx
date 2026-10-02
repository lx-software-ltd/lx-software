import { Outlet, useLocation } from 'react-router-dom'
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
  const reduced = useReducedMotion()
  const still = reduced || location.pathname !== '/'

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
