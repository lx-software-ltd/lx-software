import { describe, expect, it } from 'vitest'
import type { SiteContent } from '../src/lib/content'
import { applyHead, buildSeo } from './site-seo'

const chrome: SiteContent['chrome'] = {
  skipToContent: 'Skip to content',
  notConfigured: 'Not configured',
  menu: '[ menu ]',
  close: '[ close ]',
  carouselPrev: '[ prev ]',
  carouselNext: '[ next ]',
  carouselPrevLabel: 'Previous project',
  carouselNextLabel: 'Next project',
  carouselLabel: 'Projects',
  faqHeading: 'FAQ',
  notFoundTitle: 'Page not found',
  notFoundDescription: 'That page is not on the example site.',
  notFoundBody: 'That address is not on this site.',
  notFoundBack: '[ back to the top ]',
  updated: 'Updated',
  readMore: '[ read more ]',
  pagesLabel: 'Pages',
  breadcrumbHome: 'Home',
}

const content: SiteContent = {
  chrome,
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
  hero: {
    kicker: 'EXAMPLE',
    headline: 'Fractional CTO for startups',
    summary: 'A studio in Hong Kong.',
    scrollLabel: 'scroll',
  },
  whoIAm: { heading: 'Who I Am', paragraphs: ['Biography.'] },
  whatIDo: {
    heading: 'What I Do',
    intro: 'Services.',
    services: [{ title: 'Build', description: 'Software.', href: '/build-hong-kong' }],
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
  cta: { heading: 'Next step', body: 'Write a note.', label: '[ contact me ]', href: '/#contact' },
  faq: [{ q: 'Where?', a: 'Hong Kong.' }],
  pages: [
    {
      slug: 'build-hong-kong',
      navLabel: 'Build',
      title: 'Building software in Hong Kong',
      metaTitle: 'Build | Example Studio',
      description: 'A service page.',
      intro: 'Intro line.',
      service: 'Build',
      sections: [{ heading: 'How', paragraphs: ['Carefully.'], bullets: ['Tests', 'Docs'] }],
      faq: [{ q: 'How long?', a: 'Weeks.' }],
    },
    {
      slug: 'about',
      navLabel: 'About',
      title: 'About Sample Owner',
      metaTitle: 'About | Example Studio',
      description: 'An about page.',
      intro: 'Hello.',
      sections: [{ heading: 'Story', paragraphs: ['Once.'] }],
    },
  ],
  legal: {
    privacy: {
      title: 'Privacy Policy',
      updated: '2026-09-30',
      sections: [{ heading: 'Who', paragraphs: ['Us.'] }],
    },
    terms: {
      title: 'Terms',
      updated: '2026-09-30',
      sections: [{ heading: 'Use', paragraphs: ['Read.'] }],
    },
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
    expect(seo.llms).toContain('- Build (https://www.example.com/build-hong-kong): Software.')
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

  it('links each service to its page in the graph and llms.txt', () => {
    const seo = buildSeo(content)
    const organization = graphOf(seo.jsonld)[1]
    expect(organization.makesOffer).toEqual([
      expect.objectContaining({
        itemOffered: expect.objectContaining({ url: 'https://www.example.com/build-hong-kong' }),
      }),
    ])
    expect(seo.llms).toContain('- Build (https://www.example.com/build-hong-kong): Software.')
    expect(seo.llms).toContain('[Building software in Hong Kong](https://www.example.com/build-hong-kong)')
    expect(seo.llms).toContain('[About Sample Owner](https://www.example.com/about)')
    expect(seo.sitemap).toContain('<loc>https://www.example.com/build-hong-kong</loc>')
    expect(seo.sitemap).toContain('<loc>https://www.example.com/about</loc>')
    expect(seo.llmsFull).toContain('# Building software in Hong Kong')
    expect(seo.llmsFull).toContain('- Tests')
    expect(seo.llmsFull).toContain('How long?\nWeeks.')
  })

  it('builds a head and structured data for every route', () => {
    const seo = buildSeo(content)
    expect(seo.routes.map((route) => route.path)).toEqual([
      '/',
      '/build-hong-kong',
      '/about',
      '/privacy',
      '/terms',
      '/wechat',
    ])
    expect(seo.routes[0].jsonld).toBe(seo.jsonld)
    expect(seo.routes[0].head).toEqual(seo.head)

    const service = seo.routes[1]
    expect(service.head.title).toBe('Build | Example Studio')
    expect(service.head.description).toBe('A service page.')
    expect(service.head.url).toBe('https://www.example.com/build-hong-kong')
    const serviceGraph = graphOf(service.jsonld)
    expect(serviceGraph.map((node) => node['@type'])).toEqual([
      'WebPage',
      'BreadcrumbList',
      'Service',
      ['Organization', 'ProfessionalService'],
      'FAQPage',
    ])
    expect(serviceGraph[0].about).toEqual({ '@id': 'https://www.example.com/#service-build' })
    expect(serviceGraph[1].itemListElement).toEqual([
      expect.objectContaining({ position: 1, name: 'Home' }),
      expect.objectContaining({ position: 2, name: 'Build', item: 'https://www.example.com/build-hong-kong' }),
    ])
    expect(serviceGraph[4].mainEntity).toEqual([
      expect.objectContaining({ name: 'How long?' }),
    ])

    const about = seo.routes[2]
    const aboutGraph = graphOf(about.jsonld)
    expect(aboutGraph[0]['@type']).toEqual(['WebPage', 'AboutPage'])
    expect(aboutGraph[0].mainEntity).toEqual({ '@id': 'https://www.example.com/#person' })
    expect(aboutGraph.some((node) => node['@type'] === 'Person')).toBe(true)
    expect(aboutGraph.some((node) => node['@type'] === 'FAQPage')).toBe(false)

    const privacy = seo.routes[3]
    expect(privacy.head.title).toBe('Privacy Policy — Example Studio')
    expect(graphOf(privacy.jsonld).map((node) => node['@type'])).toEqual(['WebPage', 'BreadcrumbList'])
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
