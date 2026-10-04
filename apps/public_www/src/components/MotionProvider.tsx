import { useEffect, useSyncExternalStore, type ReactNode } from 'react'
import { MotionContext, readMotionPreference } from '../lib/motion'

const motionQueries = ['(prefers-reduced-motion: reduce)', '(prefers-reduced-data: reduce)']

function subscribe(onChange: () => void): () => void {
  const queries = motionQueries.map((query) => window.matchMedia(query))
  queries.forEach((query) => query.addEventListener('change', onChange))
  return () => {
    queries.forEach((query) => query.removeEventListener('change', onChange))
  }
}

// The pre-rendered HTML is built without a browser, so hydration starts from
// `false` and switches to the visitor's preference on the next render.
const serverSnapshot = () => false

export function MotionProvider({ children }: { children: ReactNode }) {
  const reduced = useSyncExternalStore(subscribe, readMotionPreference, serverSnapshot)

  useEffect(() => {
    document.documentElement.dataset.motion = reduced ? 'off' : 'on'
  }, [reduced])

  return <MotionContext.Provider value={reduced}>{children}</MotionContext.Provider>
}
