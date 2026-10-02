// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { TopNav } from './TopNav'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function installMatchMedia(matches: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }))
  window.matchMedia = (query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })
}

function renderNav() {
  return render(
    <MemoryRouter>
      <TopNav />
    </MemoryRouter>,
  )
}

describe('TopNav menu', () => {
  it('closes on Escape and returns focus to the toggle', () => {
    installMatchMedia(true)
    renderNav()
    const toggle = screen.getByRole('button', { name: '[ menu ]' })
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(toggle.textContent).toBe('[ close ]')
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(toggle.textContent).toBe('[ menu ]')
    expect(document.activeElement).toBe(toggle)
  })

  it('closes when a pointer goes down outside the menu', () => {
    installMatchMedia(true)
    renderNav()
    const toggle = screen.getByRole('button', { name: '[ menu ]' })
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    fireEvent.pointerDown(document.body)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
  })
})
