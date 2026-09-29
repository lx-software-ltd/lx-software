import { useRef, useState } from 'react'
import { carouselIndex } from '../lib/carouselIndex'
import type { ProjectItem } from '../lib/content'
import { useReducedMotion } from '../lib/motion'

export function ProjectCarousel({ items }: { items: ProjectItem[] }) {
  const scroller = useRef<HTMLUListElement>(null)
  const dragged = useRef(false)
  const reduced = useReducedMotion()
  const [index, setIndex] = useState(0)

  const syncIndex = () => {
    const list = scroller.current
    if (!list) return
    const offsets = Array.from(list.children).map((child) => (child as HTMLElement).offsetLeft)
    setIndex(carouselIndex(list.scrollLeft, list.scrollWidth - list.clientWidth, offsets))
  }

  const endDrag = (event: { pointerId: number }) => {
    const list = scroller.current
    if (!list) return
    list.dataset.dragging = '0'
    list.classList.remove('is-dragging')
    if (list.hasPointerCapture(event.pointerId)) list.releasePointerCapture(event.pointerId)
    syncIndex()
  }

  const scrollByCard = (direction: 1 | -1) => {
    const list = scroller.current
    const card = list?.querySelector('li')
    if (!list || !card) return
    const styles = window.getComputedStyle(list)
    const gap = Number.parseFloat(styles.columnGap || styles.gap || '0') || 0
    const step = card.getBoundingClientRect().width + gap
    const maxScroll = Math.max(0, list.scrollWidth - list.clientWidth)
    list.scrollTo({
      left: Math.min(maxScroll, Math.max(0, list.scrollLeft + direction * step)),
      behavior: reduced ? 'auto' : 'smooth',
    })
  }

  return (
    <div className="carousel" role="region" aria-roledescription="carousel" aria-label="Projects">
      <div className="carousel-toolbar">
        <button
          type="button"
          aria-label="Previous project"
          disabled={index === 0}
          onClick={() => scrollByCard(-1)}
        >
          [ prev ]
        </button>
        <span aria-live="polite">
          {index + 1} of {items.length}
        </span>
        <button
          type="button"
          aria-label="Next project"
          disabled={index >= items.length - 1}
          onClick={() => scrollByCard(1)}
        >
          [ next ]
        </button>
      </div>
      <ul
        ref={scroller}
        className="carousel-track"
        onScroll={syncIndex}
        onPointerDown={(event) => {
          if (event.pointerType !== 'mouse' || event.button !== 0) return
          const list = scroller.current
          if (!list) return
          list.dataset.dragX = String(event.clientX)
          list.dataset.dragLeft = String(list.scrollLeft)
          list.dataset.dragging = '1'
          dragged.current = false
          list.setPointerCapture(event.pointerId)
        }}
        onPointerMove={(event) => {
          const list = scroller.current
          if (!list || list.dataset.dragging !== '1') return
          const startX = Number(list.dataset.dragX)
          const startLeft = Number(list.dataset.dragLeft)
          const delta = event.clientX - startX
          if (Math.abs(delta) > 6) {
            dragged.current = true
            list.classList.add('is-dragging')
          }
          list.scrollLeft = startLeft - delta
        }}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onClickCapture={(event) => {
          if (!dragged.current) return
          event.preventDefault()
          event.stopPropagation()
          dragged.current = false
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowRight') {
            event.preventDefault()
            scrollByCard(1)
          } else if (event.key === 'ArrowLeft') {
            event.preventDefault()
            scrollByCard(-1)
          }
        }}
      >
        {items.map((item) => (
          <li key={item.title}>
            <article className="project-card">
              <pre aria-hidden="true">{item.ascii.join('\n')}</pre>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
              {item.href ? (
                <a href={item.href} rel="noreferrer">
                  [ open ]
                </a>
              ) : null}
            </article>
          </li>
        ))}
      </ul>
    </div>
  )
}
