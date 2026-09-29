import { describe, expect, it } from 'vitest'
import { buildSeo, type SeoContent } from './site-seo'

const content: SeoContent = {
  site: {
    name: 'LX Software',
    url: 'https://www.lx-software.com',
    email: 'hello@lx-software.com',
    tagline: 'Independent software studio, Hong Kong.',
    description: 'Studio site.',
    updated: '2026-09-29',
  },
  hero: { summary: 'A studio in Hong Kong.' },
  whoIAm: { heading: 'Who I Am', paragraphs: ['Placeholder biography.'] },
  whatIDo: {
    heading: 'What I Do',
    intro: 'Services.',
    services: [{ title: 'Build', description: 'Software.' }],
    skills: ['TypeScript'],
  },
  projects: {
    heading: 'Projects',
    intro: 'Selected work.',
    items: [{ title: 'Sample', description: 'A card.' }],
  },
  contact: { heading: 'Contact Me', intro: 'Write.' },
  faq: [{ q: 'Where?', a: 'Hong Kong.' }],
  legal: {
    privacy: { title: 'Privacy Policy', sections: [{ heading: 'Draft', paragraphs: ['Draft.'] }] },
    terms: { title: 'Terms', sections: [{ heading: 'Draft', paragraphs: ['Draft.'] }] },
  },
}

describe('buildSeo', () => {
  it('omits Person unless an owner name is provided', () => {
    const seo = buildSeo(content)
    const graph = JSON.parse(seo.jsonld) as { '@graph': { '@type': string }[] }
    expect(graph['@graph'].map((node) => node['@type'])).toEqual([
      'WebSite',
      'Organization',
      'FAQPage',
    ])
    expect(seo.sitemap).toContain('<lastmod>2026-09-29</lastmod>')
    expect(seo.llms).toContain('[Home](https://www.lx-software.com/)')
    expect(seo.llms).toContain('[Privacy Policy](https://www.lx-software.com/privacy)')
    expect(seo.llms).toContain('[Terms](https://www.lx-software.com/terms)')
    expect(seo.llms).toContain('[WeChat](https://www.lx-software.com/wechat)')
    expect(seo.robots).toContain('Sitemap: https://www.lx-software.com/sitemap.xml')
  })

  it('inserts a Person node when the owner name is set', () => {
    const seo = buildSeo(content, 'Site Owner')
    const graph = JSON.parse(seo.jsonld) as { '@graph': { '@type': string; name?: string }[] }
    expect(graph['@graph'].map((node) => node['@type'])).toEqual([
      'WebSite',
      'Organization',
      'Person',
      'FAQPage',
    ])
    expect(graph['@graph'][2]?.name).toBe('Site Owner')
  })
})
