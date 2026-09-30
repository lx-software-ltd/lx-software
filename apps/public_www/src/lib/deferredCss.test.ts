import { afterEach, describe, expect, it, vi } from 'vitest'
import { whenDeferredCssApplied } from './deferredCss'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('whenDeferredCssApplied', () => {
  it('turns a loaded print stylesheet into an applied one', async () => {
    const link = {
      media: 'print',
      sheet: {},
      addEventListener: vi.fn(),
    }
    vi.stubGlobal('document', {
      querySelectorAll: () => [link],
    })

    await whenDeferredCssApplied()
    expect(link.media).toBe('all')
    expect(link.addEventListener).not.toHaveBeenCalled()
  })

  it('resolves when a stylesheet is still loading', async () => {
    let onLoad: (() => void) | undefined
    const link: { media: string; sheet: unknown; addEventListener: (type: string, fn: () => void) => void } = {
      media: 'print',
      sheet: null,
      addEventListener: (type, fn) => {
        if (type === 'load') onLoad = fn
      },
    }
    vi.stubGlobal('document', {
      querySelectorAll: () => [link],
    })
    vi.stubGlobal('window', {
      setTimeout: () => 0,
    })

    const pending = whenDeferredCssApplied()
    expect(link.media).toBe('all')
    link.sheet = {}
    onLoad?.()
    await pending
  })
})