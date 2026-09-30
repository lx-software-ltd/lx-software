import { describe, expect, it } from 'vitest'
import { applyHead, buildSeo, type SeoContent } from './site-seo'

const content: SeoContent = {
  site: {
    name: 'Example Studio',
    owner: 'Sample Owner',
    role: 'Fractional CTO',
    title: 'Sample Owner | Fractional CTO, Hong Kong | Example Studio',
    url: 'https://www.example.com',
    email: 'hello@example.com',
    tagline: 'Fractional CTO for startups.',
    description: 'Studio site & "quotes".',
    keywords: ['fractional CTO', 'Hong Kong'],
    updated: '2026-09-30',
  },
  hero: { headline: 'Fractional CTO for startups', summary: 'A studio in Hong Kong.' },
  whoIAm: { heading: 'Who I Am', paragraphs: ['Biography.'] },
  whatIDo: {
    heading: 'What I Do',
    intro: 'Services.',
    services: [{ title: 'Build', description: 'Software.' }],
    skills: ['TypeScript', 'AWS'],
  },
  projects: {
    heading: 'Projects',
    intro: 'Selected work.',
    items: [
      { title: 'Live', description: 'A card.', url: 'https://live.example.com' },
      { title: 'Soon', description: 'Another card.', url: '', status: 'Coming soon' },
    ],
  },
  contact: { heading: 'Contact Me', intro: 'Write.' },
  faq: [{ q: 'Where?', a: 'Hong Kong.' }],
  legal: {
    privacy: { title: 'Privacy Policy', sections: [{ heading: 'Who', paragraphs: ['Us.'] }] },
    terms: { title: 'Terms', sections: [{ heading: 'Use', paragraphs: ['Read.'] }] },
  },
}

type Node = Record<string, unknown> & { '@type': string | string[] }

function graphOf(jsonld: string): Node[] {
  return (JSON.parse(jsonld) as { '@graph': Node[] })['@graph']
}

describe('buildSeo', () => {
  it('builds a Person + Organization graph from site.owner', () => {
    const seo = buildSeo(content)
    const graph = graphOf(seo.jsonld)
    expect(graph.map((node) => node['@type'])).toEqual([
      'WebSite',
      ['Organization', 'ProfessionalService'],
      'Person',
      'WebPage',
      'FAQPage',
    ])
    const person = graph[2]
    expect(person.name).toBe('Sample Owner')
    expect(person.jobTitle).toBe('Fractional CTO')
    expect(person.worksFor).toEqual({ '@id': 'https://www.example.com/#organization' })
    expect(person.knowsAbout).toEqual(['TypeScript', 'AWS'])
    expect(person).not.toHaveProperty('sameAs')
    const organization = graph[1]
    expect(organization.founder).toEqual({ '@id': 'https://www.example.com/#person' })
    expect(organization.makesOffer).toEqual([
      expect.objectContaining({
        itemOffered: expect.objectContaining({ '@type': 'Service', name: 'Build' }),
      }),
    ])
    expect(graph[0].keywords).toBe('fractional CTO, Hong Kong')
    expect(seo.sitemap).toContain('<lastmod>2026-09-30</lastmod>')
    expect(seo.robots).toContain('Sitemap: https://www.example.com/sitemap.xml')
  })

  it('omits Person when site.owner is empty', () => {
    const seo = buildSeo({ ...content, site: { ...content.site, owner: '' } })
    const graph = graphOf(seo.jsonld)
    expect(graph.map((node) => node['@type'])).toEqual([
      'WebSite',
      ['Organization', 'ProfessionalService'],
      'WebPage',
      'FAQPage',
    ])
    expect(graph[1]).not.toHaveProperty('founder')
    expect(seo.head.author).toBe('Example Studio')
    expect(seo.llms.startsWith('# Example Studio\n')).toBe(true)
  })

  it('adds LinkedIn as sameAs and to llms.txt when configured', () => {
    const seo = buildSeo(content, { linkedin: 'in/sample-owner' })
    const graph = graphOf(seo.jsonld)
    expect(graph[1].sameAs).toEqual(['https://www.linkedin.com/in/sample-owner'])
    expect(graph[2].sameAs).toEqual(['https://www.linkedin.com/in/sample-owner'])
    expect(seo.llms).toContain('- LinkedIn: https://www.linkedin.com/in/sample-owner')
    expect(seo.llmsFull).toContain('LinkedIn: https://www.linkedin.com/in/sample-owner')
  })

  it('lists services, projects, and pages in llms.txt', () => {
    const seo = buildSeo(content)
    expect(seo.llms.startsWith('# Sample Owner - Example Studio\n')).toBe(true)
    expect(seo.llms).toContain('Sample Owner is a Fractional CTO based in Hong Kong.')
    expect(seo.llms).toContain('- Build: Software.')
    expect(seo.llms).toContain('- Live (https://live.example.com): A card.')
    expect(seo.llms).toContain('- Soon (Coming soon): Another card.')
    expect(seo.llms).not.toContain('LinkedIn')
    expect(seo.llms).toContain('[Home](https://www.example.com/)')
    expect(seo.llms).toContain('[Privacy Policy](https://www.example.com/privacy)')
    expect(seo.llms).toContain('[Terms](https://www.example.com/terms)')
    expect(seo.llms).toContain('[WeChat](https://www.example.com/wechat)')
    expect(seo.llmsFull).toContain('Fractional CTO for startups')
    expect(seo.llmsFull).toContain('Live (https://live.example.com): A card.')
  })

  it('fills and escapes the index.html head tokens', () => {
    const seo = buildSeo(content)
    const html = applyHead(
      '<title>{{title}}</title><meta name="description" content="{{ description }}" /><p>{{noscript}}</p><b>{{other}}</b>',
      seo.head,
    )
    expect(html).toContain('<title>Sample Owner | Fractional CTO, Hong Kong | Example Studio</title>')
    expect(html).toContain('content="Studio site &amp; &quot;quotes&quot;."')
    expect(html).toContain('Email hello@example.com.')
    expect(html).toContain('<b>{{other}}</b>')
  })
})
