import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { BOAT_FLAG } from '../src/lib/boatFlag'
import { posterUrl } from '../src/lib/media'

const root = new URL('..', import.meta.url)

describe('lighthouse shell', () => {
  it('paints the harbour poster from the document, before React', () => {
    const html = readFileSync(new URL('index.html', root), 'utf8')
    expect(html).toContain(`href="${posterUrl}"`)
    expect(html).toContain('fetchpriority="high"')
    expect(html).toContain(`poster="${posterUrl}"`)
    expect(html).toContain('preload="none"')
    expect(html).toContain('id="bg-video-el"')
    expect(html).not.toContain('<img')
  })

  it('covers the junk with a sized div, because the png ratio is not 36 by 20', () => {
    const png = readFileSync(new URL('src/assets/hk-flag.png', root))
    expect(png.readUInt32BE(16)).toBe(40)
    expect(png.readUInt32BE(20)).toBe(27)
    expect(BOAT_FLAG.width).toBe(36)
    expect(BOAT_FLAG.height).toBe(20)

    const source = readFileSync(new URL('src/components/BackgroundVideo.tsx', root), 'utf8')
    expect(source).not.toMatch(/<img\b/)
    expect(source).toContain('boat-flag')
  })
})