import { useEffect, useState, type ReactNode } from 'react'
import { MotionContext, readMotionPreference } from '../lib/motion'

export function MotionProvider({ children }: { children: ReactNode }) {
  const [reduced, setReduced] = useState(readMotionPreference)

  useEffect(() => {
    document.documentElement.dataset.motion = reduced ? 'off' : 'on'
  }, [reduced])

  useEffect(() => {
    const queries = [
      window.matchMedia('(prefers-reduced-motion: reduce)'),
      window.matchMedia('(prefers-reduced-data: reduce)'),
    ]
    const update = () => setReduced(readMotionPreference())
    queries.forEach((query) => query.addEventListener('change', update))
    return () => {
      queries.forEach((query) => query.removeEventListener('change', update))
    }
  }, [])

  return <MotionContext.Provider value={reduced}>{children}</MotionContext.Provider>
}
