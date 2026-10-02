import { afterEach, describe, expect, it, vi } from 'vitest'
import { afterFirstPaint, isAppleTouch, mediaOrigin, videoSources, videoUrl } from './media'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('video urls', () => {
  it('serves same-origin files when the media host is empty', () => {
    expect(videoUrl(720, 'mp4')).toBe('/media/hk-harbour-v1-720.mp4')
  })

  it('prefixes a configured host and drops a trailing slash', () => {
    vi.stubEnv('VITE_MEDIA_BASE_URL', 'https://media.example.com/')
    expect(videoUrl(480, 'webm')).toBe('https://media.example.com/hk-harbour-v1-480.webm')
  })

  it('skips AV1 on the narrow rendition', () => {
    expect(videoSources(480)).toEqual([
      { src: '/media/hk-harbour-v1-480.mp4', type: 'video/mp4' },
    ])
    expect(videoSources(720).map((source) => source.type)).toEqual([
      'video/webm; codecs=av01.0.05M.08',
      'video/mp4',
    ])
  })

  it('serves mp4 only on iPad, including desktop-mode iPadOS', () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)',
      platform: 'iPad',
      maxTouchPoints: 5,
    })
    expect(isAppleTouch()).toBe(true)
    expect(videoSources(720)).toEqual([{ src: '/media/hk-harbour-v1-720.mp4', type: 'video/mp4' }])

    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
      platform: 'MacIntel',
      maxTouchPoints: 5,
    })
    expect(isAppleTouch()).toBe(true)
    expect(videoSources(720).map((source) => source.type)).toEqual(['video/mp4'])
  })
})

describe('mediaOrigin', () => {
  it('keeps same-origin and relative media hosts empty', () => {
    expect(mediaOrigin('')).toBe('')
    expect(mediaOrigin('/media')).toBe('')
    expect(mediaOrigin('https://media.example.com/files/')).toBe('https://media.example.com')
    expect(mediaOrigin('not a url')).toBe('')
  })
})

describe('afterFirstPaint', () => {
  it('waits for load, then runs on an idle callback', () => {
    const task = vi.fn()
    const listeners = new Map<string, () => void>()
    vi.stubGlobal('document', { readyState: 'loading' })
    vi.stubGlobal('window', {
      addEventListener: (type: string, fn: () => void) => listeners.set(type, fn),
      removeEventListener: (type: string) => listeners.delete(type),
      requestIdleCallback: (cb: () => void) => {
        cb()
        return 7
      },
      cancelIdleCallback: () => undefined,
    })

    const cancel = afterFirstPaint(task)
    expect(task).not.toHaveBeenCalled()
    listeners.get('load')?.()
    expect(task).toHaveBeenCalledOnce()
    cancel()
  })

  it('does not run the task when cancelled before load', () => {
    const task = vi.fn()
    let load: (() => void) | undefined
    vi.stubGlobal('document', { readyState: 'loading' })
    vi.stubGlobal('window', {
      addEventListener: (_type: string, fn: () => void) => {
        load = fn
      },
      removeEventListener: () => undefined,
      requestIdleCallback: (cb: () => void) => {
        cb()
        return 7
      },
      cancelIdleCallback: () => undefined,
    })

    const cancel = afterFirstPaint(task)
    cancel()
    load?.()
    expect(task).not.toHaveBeenCalled()
  })
})
