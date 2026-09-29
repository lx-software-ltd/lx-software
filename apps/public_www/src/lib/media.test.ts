import { afterEach, describe, expect, it, vi } from 'vitest'
import { videoSources, videoUrl } from './media'

afterEach(() => {
  vi.unstubAllEnvs()
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
})
