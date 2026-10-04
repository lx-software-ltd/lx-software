import { describe, expect, it } from 'vitest'
import { defaultSiteContent, findPage } from './content'

const reservedRoutes = ['privacy', 'terms', 'wechat', '404']

describe('site.json pages', () => {
  it('gives every page a unique slug that does not shadow a fixed route', () => {
    const slugs = defaultSiteContent.pages.map((page) => page.slug)
    expect(new Set(slugs).size).toBe(slugs.length)
    for (const slug of slugs) {
      expect(slug).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/)
      expect(reservedRoutes).not.toContain(slug)
    }
  })

  it('routes every service card to an existing page about that service', () => {
    for (const service of defaultSiteContent.whatIDo.services) {
      expect(service.href, service.title).toMatch(/^\/[a-z0-9-]+$/)
      const page = findPage(defaultSiteContent, service.href!.slice(1))
      expect(page, service.href).toBeDefined()
      expect(page?.service).toBe(service.title)
    }
  })

  it('keeps meta titles and descriptions inside search snippet lengths', () => {
    for (const page of defaultSiteContent.pages) {
      expect(page.metaTitle.length, page.slug).toBeLessThanOrEqual(70)
      expect(page.description.length, page.slug).toBeGreaterThanOrEqual(70)
      expect(page.description.length, page.slug).toBeLessThanOrEqual(200)
      expect(page.sections.length, page.slug).toBeGreaterThan(0)
    }
  })

  it('does not offer interim or full-time leadership', () => {
    const text = JSON.stringify(defaultSiteContent).toLowerCase()
    expect(text).not.toContain('interim leadership')
    expect(text).not.toContain('interim cto')
  })
})
