export interface SeoContent {
  site: {
    name: string
    url: string
    email: string
    tagline: string
    description: string
    updated: string
  }
  hero: { summary: string }
  whoIAm: { heading: string; paragraphs: string[] }
  whatIDo: {
    heading: string
    intro: string
    services: { title: string; description: string }[]
    skills: string[]
  }
  projects: {
    heading: string
    intro: string
    items: { title: string; description: string }[]
  }
  contact: { heading: string; intro: string }
  faq: { q: string; a: string }[]
  legal: {
    privacy: { title: string; sections: { heading: string; paragraphs: string[] }[] }
    terms: { title: string; sections: { heading: string; paragraphs: string[] }[] }
  }
}

export interface SeoFiles {
  jsonld: string
  llms: string
  llmsFull: string
  sitemap: string
  robots: string
}

export function buildSeo(content: SeoContent, ownerName = ''): SeoFiles {
  const origin = content.site.url.replace(/\/$/, '')
  const lastmod = content.site.updated
  const graph: Record<string, unknown>[] = [
    {
      '@type': 'WebSite',
      '@id': `${origin}/#website`,
      url: `${origin}/`,
      name: content.site.name,
      description: content.site.description,
      inLanguage: 'en',
    },
    {
      '@type': 'Organization',
      '@id': `${origin}/#organization`,
      name: content.site.name,
      url: `${origin}/`,
      email: content.site.email,
      logo: `${origin}/apple-touch-icon.png`,
      address: { '@type': 'PostalAddress', addressLocality: 'Hong Kong' },
    },
    {
      '@type': 'FAQPage',
      mainEntity: content.faq.map((item) => ({
        '@type': 'Question',
        name: item.q,
        acceptedAnswer: { '@type': 'Answer', text: item.a },
      })),
    },
  ]
  const name = ownerName.trim()
  if (name) {
    graph.splice(2, 0, {
      '@type': 'Person',
      '@id': `${origin}/#person`,
      name,
      url: `${origin}/`,
      email: content.site.email,
      worksFor: { '@id': `${origin}/#organization` },
    })
  }

  const pages = [
    ['/', 'Home', 'Who I am, what I do, projects, contact, and a short FAQ.'],
    ['/privacy', 'Privacy Policy', 'Draft privacy policy.'],
    ['/terms', 'Terms', 'Draft terms and conditions.'],
    ['/wechat', 'WeChat', 'WeChat contact placeholder.'],
  ]

  const llms = `# ${content.site.name}

> ${content.site.tagline}

${content.hero.summary}

## Contact

- Email: ${content.site.email}
- Telephone, WhatsApp, and WeChat appear on the contact section when they are configured at build time. Those values are not stored in the repository.

## Pages

${pages.map(([path, label, blurb]) => `- [${label}](${origin}${path}): ${blurb}`).join('\n')}

## Optional

- [Full text](${origin}/llms-full.txt): every section in plain text
`

  const blocks = [
    content.hero.summary,
    `# ${content.whoIAm.heading}`,
    ...content.whoIAm.paragraphs,
    `# ${content.whatIDo.heading}`,
    content.whatIDo.intro,
    ...content.whatIDo.services.map((service) => `${service.title}: ${service.description}`),
    `Skills: ${content.whatIDo.skills.join(', ')}`,
    `# ${content.projects.heading}`,
    content.projects.intro,
    ...content.projects.items.map((item) => `${item.title}: ${item.description}`),
    `# ${content.contact.heading}`,
    content.contact.intro,
    '# FAQ',
    ...content.faq.map((item) => `${item.q}\n${item.a}`),
    `# ${content.legal.privacy.title}`,
    ...content.legal.privacy.sections.flatMap((section) => [section.heading, ...section.paragraphs]),
    `# ${content.legal.terms.title}`,
    ...content.legal.terms.sections.flatMap((section) => [section.heading, ...section.paragraphs]),
  ]

  const urls = pages
    .map(([path]) => `  <url><loc>${origin}${path}</loc><lastmod>${lastmod}</lastmod></url>`)
    .join('\n')

  return {
    jsonld: JSON.stringify({ '@context': 'https://schema.org', '@graph': graph }, null, 2),
    llms,
    llmsFull: `${blocks.join('\n\n')}\n`,
    sitemap: `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
    robots: `User-agent: *\nAllow: /\n\nSitemap: ${origin}/sitemap.xml\n`,
  }
}
