import { linkedinUrl } from '../src/lib/linkedin.ts'

export interface SeoContent {
  site: {
    name: string
    owner: string
    role: string
    title: string
    url: string
    email: string
    tagline: string
    description: string
    keywords: string[]
    updated: string
  }
  hero: { headline: string; summary: string }
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
    items: { title: string; description: string; url?: string; status?: string }[]
  }
  contact: { heading: string; intro: string }
  faq: { q: string; a: string }[]
  legal: {
    privacy: { title: string; sections: { heading: string; paragraphs: string[] }[] }
    terms: { title: string; sections: { heading: string; paragraphs: string[] }[] }
  }
}

export interface SeoOptions {
  /** Public LinkedIn profile URL or slug. Empty omits `sameAs`. */
  linkedin?: string
}

export interface SeoHead {
  title: string
  description: string
  keywords: string
  author: string
  siteName: string
  ogImage: string
  url: string
  noscript: string
}

export interface SeoFiles {
  head: SeoHead
  jsonld: string
  llms: string
  llmsFull: string
  sitemap: string
  robots: string
}

const HEAD_TOKEN = /\{\{\s*(title|description|keywords|author|siteName|ogImage|url|noscript)\s*\}\}/g

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** Fills the `{{token}}` placeholders in `index.html` from the head block. */
export function applyHead(html: string, head: SeoHead): string {
  return html.replace(HEAD_TOKEN, (_match, key: keyof SeoHead) => escapeHtml(head[key]))
}

export function buildSeo(content: SeoContent, options: SeoOptions = {}): SeoFiles {
  const origin = content.site.url.replace(/\/$/, '')
  const lastmod = content.site.updated
  const owner = content.site.owner.trim()
  const role = content.site.role.trim()
  const linkedin = linkedinUrl(options.linkedin)
  const sameAs = linkedin ? [linkedin] : undefined
  const place = { '@type': 'PostalAddress', addressLocality: 'Hong Kong', addressCountry: 'HK' }
  const area = { '@type': 'Place', name: 'Hong Kong' }
  const organizationId = `${origin}/#organization`
  const personId = `${origin}/#person`
  const title = content.site.title.trim() || content.site.name

  const graph: Record<string, unknown>[] = [
    {
      '@type': 'WebSite',
      '@id': `${origin}/#website`,
      url: `${origin}/`,
      name: content.site.name,
      alternateName: owner ? `${owner} - ${content.site.name}` : undefined,
      description: content.site.description,
      inLanguage: 'en',
      keywords: content.site.keywords.join(', '),
      publisher: { '@id': organizationId },
      about: owner ? { '@id': personId } : undefined,
    },
    {
      '@type': ['Organization', 'ProfessionalService'],
      '@id': organizationId,
      name: content.site.name,
      url: `${origin}/`,
      email: content.site.email,
      description: content.site.tagline,
      logo: `${origin}/apple-touch-icon.png`,
      image: `${origin}/og-image.png`,
      address: place,
      areaServed: area,
      founder: owner ? { '@id': personId } : undefined,
      knowsAbout: content.whatIDo.skills,
      sameAs,
      makesOffer: content.whatIDo.services.map((service) => ({
        '@type': 'Offer',
        itemOffered: {
          '@type': 'Service',
          name: service.title,
          description: service.description,
          provider: { '@id': organizationId },
          areaServed: area,
        },
      })),
    },
    {
      '@type': 'WebPage',
      '@id': `${origin}/#webpage`,
      url: `${origin}/`,
      name: title,
      description: content.site.description,
      isPartOf: { '@id': `${origin}/#website` },
      about: owner ? { '@id': personId } : { '@id': organizationId },
      inLanguage: 'en',
      dateModified: lastmod,
    },
    {
      '@type': 'FAQPage',
      '@id': `${origin}/#faq`,
      mainEntity: content.faq.map((item) => ({
        '@type': 'Question',
        name: item.q,
        acceptedAnswer: { '@type': 'Answer', text: item.a },
      })),
    },
  ]
  if (owner) {
    graph.splice(2, 0, {
      '@type': 'Person',
      '@id': personId,
      name: owner,
      jobTitle: role || undefined,
      description: content.hero.summary,
      url: `${origin}/`,
      email: content.site.email,
      image: `${origin}/og-image.png`,
      address: place,
      worksFor: { '@id': organizationId },
      knowsAbout: content.whatIDo.skills,
      sameAs,
    })
  }

  const pages: [string, string, string][] = [
    ['/', 'Home', `${content.hero.headline}. Who I am, what I do, projects, contact, and a short FAQ.`],
    ['/privacy', content.legal.privacy.title, 'What the site collects and how contact messages are used.'],
    ['/terms', content.legal.terms.title, 'Terms for using this site.'],
    ['/wechat', 'WeChat', 'WeChat contact details.'],
  ]

  const projectLine = (item: SeoContent['projects']['items'][number]) => {
    const suffix = item.url ? ` (${item.url})` : item.status ? ` (${item.status})` : ''
    return `${item.title}${suffix}: ${item.description}`
  }

  const contactLines = [
    `- Email: ${content.site.email}`,
    linkedin ? `- LinkedIn: ${linkedin}` : null,
    '- Telephone, WhatsApp, and WeChat appear on the contact section when they are configured at build time. Those values are not stored in the repository.',
  ].filter((line): line is string => Boolean(line))

  const llms = `# ${owner ? `${owner} - ${content.site.name}` : content.site.name}

> ${content.site.tagline}

${owner ? `${owner} is a ${role} based in Hong Kong. ` : ''}${content.hero.summary}

## Services

${content.whatIDo.services.map((service) => `- ${service.title}: ${service.description}`).join('\n')}

Skills: ${content.whatIDo.skills.join(', ')}.

## Projects

${content.projects.items.map((item) => `- ${projectLine(item)}`).join('\n')}

## Contact

${contactLines.join('\n')}

## Pages

${pages.map(([path, label, blurb]) => `- [${label}](${origin}${path}): ${blurb}`).join('\n')}

## Optional

- [Full text](${origin}/llms-full.txt): every section in plain text
- [Sitemap](${origin}/sitemap.xml)
`

  const blocks = [
    `# ${owner ? `${owner} - ${content.site.name}` : content.site.name}`,
    content.site.description,
    content.hero.headline,
    content.hero.summary,
    `# ${content.whoIAm.heading}`,
    ...content.whoIAm.paragraphs,
    `# ${content.whatIDo.heading}`,
    content.whatIDo.intro,
    ...content.whatIDo.services.map((service) => `${service.title}: ${service.description}`),
    `Skills: ${content.whatIDo.skills.join(', ')}`,
    `# ${content.projects.heading}`,
    content.projects.intro,
    ...content.projects.items.map(projectLine),
    `# ${content.contact.heading}`,
    content.contact.intro,
    `Email: ${content.site.email}`,
    ...(linkedin ? [`LinkedIn: ${linkedin}`] : []),
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
    head: {
      title,
      description: content.site.description,
      keywords: content.site.keywords.join(', '),
      author: owner || content.site.name,
      siteName: content.site.name,
      ogImage: `${origin}/og-image.png`,
      url: `${origin}/`,
      noscript: `${title}. ${content.site.description} This page needs JavaScript for navigation. Email ${content.site.email}.`,
    },
    jsonld: JSON.stringify({ '@context': 'https://schema.org', '@graph': graph }, null, 2),
    llms,
    llmsFull: `${blocks.join('\n\n')}\n`,
    sitemap: `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
    robots: `User-agent: *\nAllow: /\n\nSitemap: ${origin}/sitemap.xml\n`,
  }
}
