import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const content = JSON.parse(readFileSync(join(root, 'public/content.json'), 'utf8'))
const origin = content.site.url.replace(/\/$/, '')

const graph = {
  '@context': 'https://schema.org',
  '@graph': [
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
      address: {
        '@type': 'PostalAddress',
        addressLocality: 'Hong Kong',
      },
    },
    {
      '@type': 'Person',
      '@id': `${origin}/#person`,
      name: content.site.name,
      jobTitle: 'Independent software studio',
      url: `${origin}/`,
      email: content.site.email,
      worksFor: { '@id': `${origin}/#organization` },
    },
    {
      '@type': 'FAQPage',
      mainEntity: content.faq.map((item) => ({
        '@type': 'Question',
        name: item.q,
        acceptedAnswer: { '@type': 'Answer', text: item.a },
      })),
    },
  ],
}

const indexPath = join(root, 'index.html')
const index = readFileSync(indexPath, 'utf8')
const jsonld = `<script type="application/ld+json">\n${JSON.stringify(graph, null, 2)}\n    </script>`
const marker = /<!-- jsonld:start -->[\s\S]*?<!-- jsonld:end -->/
if (!marker.test(index)) {
  throw new Error('jsonld markers missing from index.html')
}
const next = index.replace(
  marker,
  `<!-- jsonld:start -->\n    ${jsonld}\n    <!-- jsonld:end -->`,
)
writeFileSync(indexPath, next)

const pages = [
  ['/', 'Home. Who I am, what I do, projects, contact, and a short FAQ.'],
  ['/privacy', 'Draft privacy policy.'],
  ['/terms', 'Draft terms and conditions.'],
  ['/wechat', 'WeChat contact placeholder.'],
]

const llms = `# ${content.site.name}

> ${content.site.tagline}

${content.hero.summary}

## Contact

- Email: ${content.site.email}
- Telephone, WhatsApp, and WeChat appear on the contact section when they are configured at build time. Those values are not stored in the repository.

## Pages

${pages.map(([path, blurb]) => `- [${path === '/' ? 'Home' : path.slice(1)}](${origin}${path}): ${blurb}`).join('\n')}

## Optional

- [Full text](${origin}/llms-full.txt): every section in plain text
`
writeFileSync(join(root, 'public/llms.txt'), llms)

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
writeFileSync(join(root, 'public/llms-full.txt'), `${blocks.join('\n\n')}\n`)

const today = '2026-09-29'
const urls = ['/', '/privacy', '/terms', '/wechat']
  .map(
    (path) => `  <url><loc>${origin}${path}</loc><lastmod>${today}</lastmod></url>`,
  )
  .join('\n')
writeFileSync(
  join(root, 'public/sitemap.xml'),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
)
writeFileSync(
  join(root, 'public/robots.txt'),
  `User-agent: *\nAllow: /\n\nSitemap: ${origin}/sitemap.xml\n`,
)
