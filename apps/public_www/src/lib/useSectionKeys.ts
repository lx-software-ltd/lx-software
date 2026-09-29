import { useEffect } from 'react'
import { pageSections } from './sections'

function scrollToId(id: string, smooth: boolean) {
  if (id === 'top') {
    window.scrollTo({ top: 0, behavior: smooth ? 'smooth' : 'auto' })
    return
  }
  document.getElementById(id)?.scrollIntoView({
    behavior: smooth ? 'smooth' : 'auto',
    block: 'start',
  })
}

export function useSectionKeys(enabled: boolean, smooth: boolean) {
  useEffect(() => {
    if (!enabled) return

    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.metaKey || event.ctrlKey) return
      const focused = document.activeElement
      if (focused && focused !== document.body && focused !== document.documentElement) return
      const down = event.key === 'ArrowDown' || event.key === 'j'
      const up = event.key === 'ArrowUp' || event.key === 'k'
      if (!down && !up) return

      const ids = ['top', ...pageSections.map((section) => section.id)]
      const marker = window.scrollY + 80
      let index = 0
      ids.forEach((id, position) => {
        const node = id === 'top' ? document.body : document.getElementById(id)
        if (!node) return
        const top = id === 'top' ? 0 : node.getBoundingClientRect().top + window.scrollY
        if (top <= marker) index = position
      })
      const next = ids[Math.min(ids.length - 1, Math.max(0, index + (down ? 1 : -1)))]
      if (!next || next === ids[index]) return
      event.preventDefault()
      scrollToId(next, smooth)
      history.replaceState(null, '', next === 'top' ? '/' : `#${next}`)
    }

    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled, smooth])
}
