import { describe, expect, it } from 'vitest'
import {
  applyRouteHead,
  assertInlineSafe,
  embedJsonLd,
  injectAppHtml,
  inlineStylesheets,
  routeOutputPaths,
} from './prerender'
import type { SeoHead } from './site-seo'

const template = `<!doctype html>
<html lang="en">
  <head>
    <title>Home | Example</title>
    <meta name="description" content="Home description." />
    <link rel="canonical" href="https://www.example.com/" />
    <meta property="og:title" content="Home | Example" />
    <meta property="og:description" content="Home description." />
    <meta property="og:url" content="https://www.example.com/" />
    <meta property="og:image" content="https://www.example.com/og-image.png" />
    <meta property="og:image:alt" content="Home | Example" />
    <meta name="twitter:title" content="Home | Example" />
    <meta name="twitter:description" content="Home description." />
    <script type="module" crossorigin src="/assets/index-abc.js"></script>
        <link rel="preload" href="/assets/index-abc.css" as="style" crossorigin />
<link rel="stylesheet" media="print" data-defer-css crossorigin href="/assets/index-abc.css">
    <noscript><link rel="stylesheet" data-static-css href="/assets/index-abc.css" /></noscript>
    <script type="application/ld+json">
{ "@context": "https://schema.org", "@graph": [] }
    </script>
  </head>
  <body>
    <div id="root"></div>
    <noscript>
      <p style="color:#fff">
        Home | Example. Home description. Email hello@example.com.
      </p>
    </noscript>
  </body>
</html>`

const head: SeoHead = {
  title: 'About "Sample" & Co | Example',
  description: 'An <about> page.',
  keywords: 'a, b',
  author: 'Sample Owner',
  siteName: 'Example',
  ogImage: 'https://www.example.com/og-image.png',
  url: 'https://www.example.com/about',
  noscript: 'About page. Email hello@example.com.',
}

describe('routeOutputPaths', () => {
  it('writes the home shell once and other routes as a folder index plus a flat file', () => {
    expect(routeOutputPaths('/')).toEqual(['index.html'])
    expect(routeOutputPaths('/about')).toEqual(['about/index.html', 'about.html'])
    expect(routeOutputPaths('/privacy/')).toEqual(['privacy/index.html', 'privacy.html'])
  })
})

describe('injectAppHtml', () => {
  it('fills the empty root and refuses a template without one', () => {
    expect(injectAppHtml(template, '<main><h1>Hi</h1></main>')).toContain(
      '<div id="root"><main><h1>Hi</h1></main></div>',
    )
    expect(() => injectAppHtml('<div id="root"><p>x</p></div>', '')).toThrow(/empty #root/)
  })
})

describe('applyRouteHead', () => {
  it('rewrites every per-page head tag with escaped values and swaps the JSON-LD', () => {
    const html = applyRouteHead(template, head, '{ "@graph": [ { "@type": "AboutPage" } ] }')
    expect(html).toContain('<title>About &quot;Sample&quot; &amp; Co | Example</title>')
    expect(html).toContain('<meta name="description" content="An &lt;about&gt; page." />')
    expect(html).toContain('<link rel="canonical" href="https://www.example.com/about" />')
    expect(html).toContain('<meta property="og:title" content="About &quot;Sample&quot; &amp; Co | Example" />')
    expect(html).toContain('<meta property="og:description" content="An &lt;about&gt; page." />')
    expect(html).toContain('<meta property="og:url" content="https://www.example.com/about" />')
    expect(html).toContain('<meta property="og:image:alt" content="About &quot;Sample&quot; &amp; Co | Example" />')
    expect(html).toContain('<meta name="twitter:title" content="About &quot;Sample&quot; &amp; Co | Example" />')
    expect(html).toContain('<meta name="twitter:description" content="An &lt;about&gt; page." />')
    expect(html).toContain('About page. Email hello@example.com.')
    expect(html).not.toContain('Home | Example. Home description.')
    expect(html).toContain('{ "@graph": [ { "@type": "AboutPage" } ] }')
    expect(html).not.toContain('"@graph": []')
    expect(html).toContain('<meta property="og:image" content="https://www.example.com/og-image.png" />')
  })

  it('fails loudly when index.html lost a tag it rewrites', () => {
    const broken = template.replace(/<link rel="canonical"[^>]*>/, '')
    expect(() => applyRouteHead(broken, head, '{}')).toThrow(/canonical/)
  })

  it('keeps `$` sequences in JSON-LD literal', () => {
    const html = applyRouteHead(template, head, '{ "price": "$1 and $& and $`" }')
    expect(html).toContain('{ "price": "$1 and $& and $`" }')
  })

  it('escapes a script closer inside JSON-LD', () => {
    const payload = '{ "name": "</script><script>alert(1)</script>" }'
    const html = applyRouteHead(template, head, payload)
    expect(html).toContain(embedJsonLd(payload))
    expect(html).not.toContain('</script><script>')
    const embedded = html.match(/<script type="application\/ld\+json">\n([\s\S]*?)\n {4}<\/script>/)
    expect(JSON.parse(embedded?.[1] ?? '')).toEqual({ name: '</script><script>alert(1)</script>' })
  })

  it('fails when the JSON-LD script tag is gone', () => {
    const broken = template.replace(/<script type="application\/ld\+json">[\s\S]*?<\/script>/, '')
    expect(() => applyRouteHead(broken, head, '{}')).toThrow(/JSON-LD/)
  })
})

describe('inlineStylesheets', () => {
  it('replaces the deferred preload / print / noscript trio with one style element', () => {
    const { html, inlined } = inlineStylesheets(template, (href) => `/* ${href} */ body { color: red }`)
    expect(inlined).toEqual(['/assets/index-abc.css'])
    expect(html).toContain(
      '<style data-inlined-css="/assets/index-abc.css">/* /assets/index-abc.css */ body { color: red }</style>',
    )
    expect(html).not.toContain('data-defer-css')
    expect(html).not.toContain('data-static-css')
    expect(html).not.toContain('as="style"')
    expect(html).toContain('<script type="module" crossorigin src="/assets/index-abc.js"></script>')
  })

  it('leaves a document without deferred links alone', () => {
    const { html, inlined } = inlineStylesheets('<head></head>', () => '')
    expect(inlined).toEqual([])
    expect(html).toBe('<head></head>')
  })
})

describe('assertInlineSafe', () => {
  it('refuses CSS that would close the style element', () => {
    expect(() => assertInlineSafe('a { content: "</style>" }', '/x.css')).toThrow(/x\.css/)
    expect(() => assertInlineSafe('a { color: red }', '/x.css')).not.toThrow()
  })
})
