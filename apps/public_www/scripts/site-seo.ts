import type { ContentPage, SiteContent } from '../src/lib/content.ts'
import { linkedinUrl } from '../src/lib/linkedin.ts'

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

/** Head values and structured data for one pre-rendered route. */
export interface RouteSeo {
  path: string
  head: SeoHead
  jsonld: string
}

export interface SeoFiles {
  /** Home page head; `routes` carries every page including this one. */
  head: SeoHead
  jsonld: string
  routes: RouteSeo[]
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

type JsonLdNode = Record<string, unknown>

function jsonld(graph: JsonLdNode[]): string {
  return JSON.stringify({ '@context': 'https://schema.org', '@graph': graph }, null, 2)
}

export function buildSeo(content: SiteContent, options: SeoOptions = {}): SeoFiles {
  const origin = content.site.url.replace(/\/$/, '')
  const lastmod = content.site.updated
  const owner = content.site.owner.trim()
  const role = content.site.role.trim()
  const linkedin = linkedinUrl(options.linkedin)
  const sameAs = linkedin ? [linkedin] : undefined
  const place = { '@type': 'PostalAddress', addressLocality: 'Hong Kong', addressCountry: 'HK' }
  const area = { '@type': 'Place', name: 'Hong Kong' }
  const websiteId = `${origin}/#website`
  const organizationId = `${origin}/#organization`
  const personId = `${origin}/#person`
  const title = content.site.title.trim() || content.site.name
  const pageUrl = (page: ContentPage) => `${origin}/${page.slug}`
  const serviceId = (serviceTitle: string) =>
    `${origin}/#service-${serviceTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`
  const pageForService = (serviceTitle: string) =>
    content.pages.find((page) => page.service === serviceTitle)

  const serviceNodes = content.whatIDo.services.map((service) => {
    const page = pageForService(service.title)
    return {
      '@type': 'Service',
      '@id': serviceId(service.title),
      name: service.title,
      description: service.description,
      provider: { '@id': organizationId },
      areaServed: area,
      url: page ? pageUrl(page) : service.href ? `${origin}${service.href}` : undefined,
    }
  })

  const graph: JsonLdNode[] = [
    {
      '@type': 'WebSite',
      '@id': websiteId,
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
      makesOffer: serviceNodes.map((service) => ({
        '@type': 'Offer',
        itemOffered: service,
      })),
    },
    {
      '@type': 'WebPage',
      '@id': `${origin}/#webpage`,
      url: `${origin}/`,
      name: title,
      description: content.site.description,
      isPartOf: { '@id': websiteId },
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
  const personNode: JsonLdNode | undefined = owner
    ? {
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
      }
    : undefined
  if (personNode) graph.splice(2, 0, personNode)

  const head = (pageTitle: string, description: string, path: string): SeoHead => ({
    title: pageTitle,
    description,
    keywords: content.site.keywords.join(', '),
    author: owner || content.site.name,
    siteName: content.site.name,
    ogImage: `${origin}/og-image.png`,
    url: `${origin}${path}`,
    noscript: `${pageTitle}. ${description} This page needs JavaScript for navigation. Email ${content.site.email}.`,
  })

  const breadcrumb = (path: string, label: string): JsonLdNode => ({
    '@type': 'BreadcrumbList',
    '@id': `${origin}${path}#breadcrumb`,
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: content.chrome.breadcrumbHome, item: `${origin}/` },
      { '@type': 'ListItem', position: 2, name: label, item: `${origin}${path}` },
    ],
  })

  const simplePage = (path: string, name: string, description: string): RouteSeo => ({
    path,
    head: head(`${name} — ${content.site.name}`, description, path),
    jsonld: jsonld([
      {
        '@type': 'WebPage',
        '@id': `${origin}${path}#webpage`,
        url: `${origin}${path}`,
        name,
        description,
        isPartOf: { '@id': websiteId },
        inLanguage: 'en',
        dateModified: lastmod,
        breadcrumb: { '@id': `${origin}${path}#breadcrumb` },
      },
      breadcrumb(path, name),
    ]),
  })

  const contentPage = (page: ContentPage): RouteSeo => {
    const path = `/${page.slug}`
    const url = pageUrl(page)
    const isAbout = page.slug === 'about'
    const service = page.service ? serviceNodes.find((node) => node.name === page.service) : undefined
    const nodes: JsonLdNode[] = [
      {
        '@type': isAbout ? ['WebPage', 'AboutPage'] : 'WebPage',
        '@id': `${url}#webpage`,
        url,
        name: page.metaTitle,
        headline: page.title,
        description: page.description,
        isPartOf: { '@id': websiteId },
        about: service ? { '@id': service['@id'] } : personNode ? { '@id': personId } : { '@id': organizationId },
        mainEntity: isAbout && personNode ? { '@id': personId } : service ? { '@id': service['@id'] } : undefined,
        inLanguage: 'en',
        dateModified: lastmod,
        breadcrumb: { '@id': `${url}#breadcrumb` },
      },
      breadcrumb(path, page.navLabel),
    ]
    if (service) nodes.push({ ...service, provider: { '@id': organizationId } })
    if (isAbout && personNode) nodes.push(personNode)
    nodes.push({ '@type': ['Organization', 'ProfessionalService'], '@id': organizationId, name: content.site.name, url: `${origin}/` })
    if (page.faq && page.faq.length > 0) {
      nodes.push({
        '@type': 'FAQPage',
        '@id': `${url}#faq`,
        mainEntity: page.faq.map((item) => ({
          '@type': 'Question',
          name: item.q,
          acceptedAnswer: { '@type': 'Answer', text: item.a },
        })),
      })
    }
    return { path, head: head(page.metaTitle, page.description, path), jsonld: jsonld(nodes) }
  }

  const homeHead = head(title, content.site.description, '/')
  const routes: RouteSeo[] = [
    { path: '/', head: homeHead, jsonld: jsonld(graph) },
    ...content.pages.map(contentPage),
    simplePage('/privacy', content.legal.privacy.title, 'What the site collects and how contact messages are used.'),
    simplePage('/terms', content.legal.terms.title, 'Terms for using this site.'),
    simplePage('/wechat', 'WeChat', 'WeChat contact details.'),
  ]

  const pages: [string, string, string][] = [
    ['/', 'Home', `${content.hero.headline}. Who I am, what I do, projects, contact, and a short FAQ.`],
    ...content.pages.map(
      (page): [string, string, string] => [`/${page.slug}`, page.title, page.description],
    ),
    ['/privacy', content.legal.privacy.title, 'What the site collects and how contact messages are used.'],
    ['/terms', content.legal.terms.title, 'Terms for using this site.'],
    ['/wechat', 'WeChat', 'WeChat contact details.'],
  ]

  const projectLine = (item: SiteContent['projects']['items'][number]) => {
    const suffix = item.url ? ` (${item.url})` : item.status ? ` (${item.status})` : ''
    return `${item.title}${suffix}: ${item.description}`
  }

  const serviceLine = (service: SiteContent['whatIDo']['services'][number]) => {
    const page = pageForService(service.title)
    const link = page ? ` (${pageUrl(page)})` : ''
    return `- ${service.title}${link}: ${service.description}`
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

${content.whatIDo.services.map(serviceLine).join('\n')}

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

  const pageBlocks = (page: ContentPage) => [
    `# ${page.title}`,
    page.intro,
    ...page.sections.flatMap((section) => [
      section.heading,
      ...(section.paragraphs ?? []),
      ...(section.bullets ?? []).map((bullet) => `- ${bullet}`),
    ]),
    ...(page.faq ?? []).map((item) => `${item.q}\n${item.a}`),
  ]

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
    `# ${content.chrome.faqHeading}`,
    ...content.faq.map((item) => `${item.q}\n${item.a}`),
    ...content.pages.flatMap(pageBlocks),
    `# ${content.legal.privacy.title}`,
    ...content.legal.privacy.sections.flatMap((section) => [section.heading, ...section.paragraphs]),
    `# ${content.legal.terms.title}`,
    ...content.legal.terms.sections.flatMap((section) => [section.heading, ...section.paragraphs]),
  ]

  const urls = pages
    .map(([path]) => `  <url><loc>${origin}${path}</loc><lastmod>${lastmod}</lastmod></url>`)
    .join('\n')

  return {
    head: homeHead,
    jsonld: jsonld(graph),
    routes,
    llms,
    llmsFull: `${blocks.join('\n\n')}\n`,
    sitemap: `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
    robots: `User-agent: *\nAllow: /\n\nSitemap: ${origin}/sitemap.xml\n`,
  }
}
