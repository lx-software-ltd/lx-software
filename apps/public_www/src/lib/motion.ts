import { createContext, useContext } from 'react'

export const MotionContext = createContext(false)

export function readMotionPreference(): boolean {
  if (typeof window === 'undefined') return false
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const reducedData = window.matchMedia('(prefers-reduced-data: reduce)').matches
  const saveData = Boolean(
    (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData,
  )
  return reducedMotion || reducedData || saveData
}

export function useReducedMotion(): boolean {
  return useContext(MotionContext)
}
