// @vitest-environment happy-dom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
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

function Where() {
  const { pathname, search, hash } = useLocation()
  return <span data-testid="where">{`${pathname}${search}${hash}`}</span>
}

function renderAt(path: string) {
  installMatchMedia()
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Where />
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
    expect(screen.getByTestId('where').textContent).toBe('/')
  })

  it('keeps the query and hash from the cached star redirect', async () => {
    renderAt('/*?utm=gbp#contact')
    await screen.findByRole('heading', { level: 1 })
    expect(screen.getByTestId('where').textContent).toBe('/?utm=gbp#contact')
  })

  it('keeps an unknown path on the not-found page', async () => {
    renderAt('/careers')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeTruthy()
  })
})
