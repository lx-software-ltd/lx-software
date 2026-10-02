import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { defaultSiteContent } from './content'
import { useReducedMotion } from './motion'

export const pageSections = [
  { id: 'who-i-am', label: defaultSiteContent.whoIAm.heading },
  { id: 'what-i-do', label: defaultSiteContent.whatIDo.heading },
  { id: 'projects', label: defaultSiteContent.projects.heading },
  { id: 'contact', label: defaultSiteContent.contact.heading },
] as const

export type SectionId = (typeof pageSections)[number]['id']

const sectionIds = pageSections.map((section) => section.id)

function isSectionId(id: string): id is SectionId {
  return sectionIds.some((sectionId) => sectionId === id)
}

function scrollToElement(id: string, reduced: boolean) {
  const behavior: ScrollBehavior = reduced ? 'auto' : 'smooth'
  if (id === 'top') {
    window.scrollTo({ top: 0, behavior })
    return
  }
  document.getElementById(id)?.scrollIntoView({ behavior, block: 'start' })
}

export function useSections() {
  const location = useLocation()
  const navigate = useNavigate()
  const reduced = useReducedMotion()
  const onHome = location.pathname === '/'
  const [observed, setObserved] = useState<SectionId | null>(null)
  const [trackedHome, setTrackedHome] = useState(onHome)
  if (trackedHome !== onHome) {
    setTrackedHome(onHome)
    setObserved(null)
  }
  const active = onHome ? observed : null

  useEffect(() => {
    if (!onHome) return
    const nodes = sectionIds
      .map((id) => document.getElementById(id))
      .filter((node): node is HTMLElement => node !== null)
    if (nodes.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (!visible) return
        const id = visible.target.id
        if (isSectionId(id)) setObserved(id)
      },
      { rootMargin: '-40% 0px -55% 0px', threshold: [0, 0.25, 0.5, 1] },
    )
    nodes.forEach((node) => observer.observe(node))
    return () => observer.disconnect()
  }, [onHome])

  useEffect(() => {
    if (!onHome) return
    const id = location.hash.replace(/^#/, '')
    scrollToElement(id || 'top', reduced)
  }, [onHome, location.hash, reduced])

  const scrollTo = (id: string) => {
    const targetHash = id === 'top' ? '' : `#${id}`
    const alreadyThere = location.pathname === '/' && location.hash === targetHash
    scrollToElement(id, reduced)
    if (alreadyThere) return
    navigate(targetHash ? `/${targetHash}` : '/')
  }

  return {
    ids: sectionIds,
    active,
    scrollTo,
  }
}
