import { describe, expect, it } from 'vitest'
import { deferStylesheetLinks, fontPreloadTags } from './index-html'

describe('index html asset tags', () => {
  it('preloads a stylesheet without blocking first paint', () => {
    const html = '<head>\n<link rel="stylesheet" crossorigin href="/assets/index-abc.css">\n</head>'
    const next = deferStylesheetLinks(html)
    expect(next).toContain('<link rel="preload" href="/assets/index-abc.css" as="style" crossorigin />')
    expect(next).toContain('media="print" data-defer-css')
    expect(next).toContain('<noscript><link rel="stylesheet" data-static-css href="/assets/index-abc.css" /></noscript>')
    const twice = deferStylesheetLinks(next)
    expect(twice.match(/rel="preload"/g)).toHaveLength(1)
    expect(twice.match(/media="print"/g)).toHaveLength(1)
  })

  it('preloads woff2 fonts with crossorigin and skips woff', () => {
    const tags = fontPreloadTags([
      'assets/ibm-plex-mono-latin-400-normal-abc.woff2',
      'assets/ibm-plex-mono-latin-400-normal-abc.woff',
      'assets/index-abc.js',
    ])
    expect(tags).toBe(
      '    <link rel="preload" href="/assets/ibm-plex-mono-latin-400-normal-abc.woff2" as="font" type="font/woff2" crossorigin />',
    )
  })
})
