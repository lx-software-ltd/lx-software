import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { deferStylesheetLinks, fontPreloadTags } from './scripts/index-html.ts'
import { applyHead, buildSeo, type SeoFiles, type SeoOptions } from './scripts/site-seo.ts'
import { defaultSiteContent } from './src/lib/content.ts'
import { mediaOrigin } from './src/lib/media.ts'

function siteSeo(options: SeoOptions): Plugin {
  let files: SeoFiles | undefined
  const load = () => {
    files ??= buildSeo(defaultSiteContent, options)
    return files
  }
  const types: Record<string, string> = {
    '/llms.txt': 'text/plain; charset=utf-8',
    '/llms-full.txt': 'text/plain; charset=utf-8',
    '/robots.txt': 'text/plain; charset=utf-8',
    '/sitemap.xml': 'application/xml; charset=utf-8',
  }
  return {
    name: 'site-seo',
    transformIndexHtml(html) {
      const seo = load()
      const filled = applyHead(html, seo.head)
      if (filled.includes('application/ld+json')) return filled
      const block = `    <script type="application/ld+json">\n${seo.jsonld}\n    </script>\n`
      return filled.replace('</head>', `${block}  </head>`)
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = req.url?.split('?')[0] ?? ''
        const type = types[path]
        if (!type) {
          next()
          return
        }
        const seo = load()
        const body =
          path === '/llms.txt'
            ? seo.llms
            : path === '/llms-full.txt'
              ? seo.llmsFull
              : path === '/robots.txt'
                ? seo.robots
                : seo.sitemap
        res.setHeader('Content-Type', type)
        res.end(body)
      })
    },
    generateBundle() {
      const seo = load()
      this.emitFile({ type: 'asset', fileName: 'llms.txt', source: seo.llms })
      this.emitFile({ type: 'asset', fileName: 'llms-full.txt', source: seo.llmsFull })
      this.emitFile({ type: 'asset', fileName: 'robots.txt', source: seo.robots })
      this.emitFile({ type: 'asset', fileName: 'sitemap.xml', source: seo.sitemap })
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const origin = mediaOrigin(process.env.VITE_MEDIA_BASE_URL || env.VITE_MEDIA_BASE_URL || '')
  const linkedin = process.env.VITE_CONTACT_LINKEDIN || env.VITE_CONTACT_LINKEDIN || ''

  return {
    plugins: [
      react(),
      siteSeo({ linkedin }),
      {
        name: 'media-preconnect',
        transformIndexHtml(html: string) {
          if (!origin) return html
          const tag = `<link rel="preconnect" href="${origin}" />`
          if (html.includes(tag)) return html
          return html.replace('</head>', `    ${tag}\n  </head>`)
        },
      },
      {
        name: 'lcp-assets',
        transformIndexHtml: {
          order: 'post',
          handler(html, ctx) {
            const bundle = ctx.bundle
            if (!bundle) return html
            const fonts = fontPreloadTags(
              Object.values(bundle)
                .filter((item) => item.type === 'asset')
                .map((item) => item.fileName),
            )
            const withFonts = fonts ? html.replace('</head>', `${fonts}\n  </head>`) : html
            return deferStylesheetLinks(withFonts)
          },
        },
      },
    ],
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (
              id.includes('node_modules/react-dom') ||
              id.includes('node_modules/react/') ||
              id.includes('node_modules/scheduler') ||
              id.includes('node_modules/react-router')
            ) {
              return 'react'
            }
          },
        },
      },
    },
  }
})
