// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { ProjectItem } from '../lib/content'
import { ProjectCarousel } from './ProjectCarousel'

const items: ProjectItem[] = [
  { title: 'Live', description: 'A card.', url: 'https://live.example.com' },
  { title: 'Soon', description: 'Another card.', status: 'Coming soon' },
]

afterEach(() => {
  cleanup()
})

function armScroller(list: HTMLElement) {
  const cards = [...list.querySelectorAll('li')]
  cards.forEach((card, index) => {
    Object.defineProperty(card, 'offsetLeft', { configurable: true, value: index * 320 })
    card.getBoundingClientRect = () =>
      ({
        width: 300,
        height: 120,
        top: 0,
        left: index * 320,
        right: 300,
        bottom: 120,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect
  })
  let left = 0
  Object.defineProperty(list, 'scrollLeft', {
    configurable: true,
    get: () => left,
    set: (value: number) => {
      left = value
    },
  })
  Object.defineProperty(list, 'scrollWidth', { configurable: true, value: 320 * cards.length })
  Object.defineProperty(list, 'clientWidth', { configurable: true, value: 300 })
  list.scrollTo = (options?: ScrollToOptions | number) => {
    if (typeof options === 'object' && options && typeof options.left === 'number') left = options.left
    list.dispatchEvent(new Event('scroll'))
  }
}

describe('ProjectCarousel', () => {
  it('moves with the next and previous buttons', () => {
    render(<ProjectCarousel items={items} />)
    const list = screen.getByRole('list', { name: 'Projects' })
    expect(list.tabIndex).toBe(0)
    armScroller(list)
    const status = screen.getByText('1 of 2')
    fireEvent.click(screen.getByRole('button', { name: 'Next project' }))
    expect(status.textContent).toBe('2 of 2')
    fireEvent.click(screen.getByRole('button', { name: 'Previous project' }))
    expect(status.textContent).toBe('1 of 2')
  })

  it('keeps focus on a boundary control that is aria-disabled', () => {
    render(<ProjectCarousel items={items} />)
    const prev = screen.getByRole('button', { name: 'Previous project' })
    expect(prev.getAttribute('aria-disabled')).toBe('true')
    expect(prev.hasAttribute('disabled')).toBe(false)
    prev.focus()
    fireEvent.click(prev)
    expect(document.activeElement).toBe(prev)
    expect(screen.getByText('1 of 2')).toBeTruthy()

    const list = screen.getByRole('list', { name: 'Projects' })
    armScroller(list)
    const next = screen.getByRole('button', { name: 'Next project' })
    fireEvent.click(next)
    expect(next.getAttribute('aria-disabled')).toBe('true')
    next.focus()
    fireEvent.click(next)
    expect(document.activeElement).toBe(next)
    expect(screen.getByText('2 of 2')).toBeTruthy()
  })

  it('ignores arrow keys at the ends and does not block page scroll', () => {
    render(<ProjectCarousel items={items} />)
    const list = screen.getByRole('list', { name: 'Projects' })
    armScroller(list)
    expect(fireEvent.keyDown(list, { key: 'ArrowLeft' })).toBe(true)
    expect(screen.getByText('1 of 2').textContent).toBe('1 of 2')
    expect(fireEvent.keyDown(list, { key: 'ArrowRight' })).toBe(false)
    expect(screen.getByText('2 of 2').textContent).toBe('2 of 2')
    expect(fireEvent.keyDown(list, { key: 'ArrowRight' })).toBe(true)
    expect(screen.getByText('2 of 2').textContent).toBe('2 of 2')
  })
})
