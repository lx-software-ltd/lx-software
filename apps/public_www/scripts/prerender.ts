import type { SeoHead } from './site-seo.ts'

/**
 * Pure HTML rewrites used by the `prerenderPages` plugin in `vite.config.ts`.
 * The built `dist/index.html` is the template: the plugin renders each route
 * with `src/entry-server.tsx`, puts the markup inside `#root`, swaps the head
 * for that route's values, and inlines the stylesheet so the pre-rendered
 * body is styled on first paint instead of flashing unstyled.
 */

function escapeAttr(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * `dist/`-relative files for a route. `/` is the shell. Another route is
 * written twice: `about/index.html` for static servers that resolve a
 * directory index (`/about/`), and `about.html` for Vite preview and the
 * deploy script, which uploads it to the extensionless S3 key `about` so
 * CloudFront answers `/about` with that page instead of the SPA fallback.
 */
export function routeOutputPaths(path: string): string[] {
  const trimmed = path.replace(/^\/+|\/+$/g, '')
  return trimmed ? [`${trimmed}/index.html`, `${trimmed}.html`] : ['index.html']
}

export function injectAppHtml(template: string, appHtml: string): string {
  const marker = '<div id="root"></div>'
  if (!template.includes(marker)) throw new Error('index.html has no empty #root to pre-render into')
  return template.replace(marker, `<div id="root">${appHtml}</div>`)
}

function replaceTag(html: string, pattern: RegExp, replacement: string, what: string): string {
  if (!pattern.test(html)) throw new Error(`index.html is missing ${what}`)
  // A function keeps `$&` / `$1` in the replacement (JSON-LD text) literal.
  return html.replace(pattern, () => replacement)
}

/** Rewrites title, description, canonical, Open Graph, Twitter, noscript and JSON-LD for one route. */
export function applyRouteHead(template: string, head: SeoHead, jsonld: string): string {
  const title = escapeAttr(head.title)
  const description = escapeAttr(head.description)
  const url = escapeAttr(head.url)
  let html = template
  html = replaceTag(html, /<title>[^<]*<\/title>/, `<title>${title}</title>`, '<title>')
  html = replaceTag(
    html,
    /<meta name="description" content="[^"]*" \/>/,
    `<meta name="description" content="${description}" />`,
    'meta description',
  )
  html = replaceTag(
    html,
    /<link rel="canonical" href="[^"]*" \/>/,
    `<link rel="canonical" href="${url}" />`,
    'canonical link',
  )
  for (const [property, value] of [
    ['og:title', title],
    ['og:description', description],
    ['og:url', url],
    ['og:image:alt', title],
  ] as const) {
    html = replaceTag(
      html,
      new RegExp(`<meta property="${property}" content="[^"]*" />`),
      `<meta property="${property}" content="${value}" />`,
      property,
    )
  }
  for (const [name, value] of [
    ['twitter:title', title],
    ['twitter:description', description],
  ] as const) {
    html = replaceTag(
      html,
      new RegExp(`<meta name="${name}" content="[^"]*" />`),
      `<meta name="${name}" content="${value}" />`,
      name,
    )
  }
  const noscript = /(<noscript>\s*<p[^>]*>)[\s\S]*?(<\/p>\s*<\/noscript>)/
  if (!noscript.test(html)) throw new Error('index.html is missing noscript paragraph')
  html = html.replace(
    noscript,
    (_match, open: string, close: string) => `${open}\n        ${escapeAttr(head.noscript)}\n      ${close}`,
  )
  html = replaceTag(
    html,
    /<script type="application\/ld\+json">[\s\S]*?<\/script>/,
    `<script type="application/ld+json">\n${jsonld}\n    </script>`,
    'JSON-LD script',
  )
  return html
}

/**
 * Replaces the deferred stylesheet trio written by `deferStylesheetLinks`
 * (preload, `media="print"` link, noscript fallback) with one inline
 * `<style>`. Returns the hrefs it inlined so the caller can check coverage.
 */
export function inlineStylesheets(html: string, readCss: (href: string) => string): { html: string; inlined: string[] } {
  const inlined: string[] = []
  const trio =
    /[ \t]*<link rel="preload" href="([^"]+\.css)" as="style" crossorigin \/>\s*<link rel="stylesheet" media="print" data-defer-css[^>]*>\s*<noscript><link rel="stylesheet" data-static-css href="[^"]+" \/><\/noscript>/g
  const out = html.replace(trio, (_match, href: string) => {
    inlined.push(href)
    return `    <style data-inlined-css="${escapeAttr(href)}">${readCss(href)}</style>`
  })
  return { html: out, inlined }
}

/** The CSS must stay inside the `<style>` element it was inlined into. */
export function assertInlineSafe(css: string, href: string): void {
  if (/<\/style/i.test(css)) throw new Error(`${href} contains "</style" and cannot be inlined`)
}
