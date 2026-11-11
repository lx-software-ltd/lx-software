// @vitest-environment happy-dom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { AppRoutes } from './App'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function installMatchMedia() {
  const queryList = {
    matches: false,
    media: '',
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }
  vi.stubGlobal('matchMedia', () => queryList)
}

function renderAt(path: string) {
  installMatchMedia()
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  )
}

describe('legacy star path', () => {
  it('opens the home page for the cached apex redirect', async () => {
    renderAt('/*')
    const heading = await screen.findByRole('heading', { level: 1 })
    expect(heading.textContent).toContain('Fractional CTO & CIO for Hong Kong startups')
    expect(screen.queryByRole('heading', { name: 'Page not found' })).toBeNull()
  })

  it('keeps an unknown path on the not-found page', async () => {
    renderAt('/careers')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeTruthy()
  })
})
