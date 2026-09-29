import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { buildSeo, type SeoContent } from './scripts/site-seo.ts'

function siteSeo(ownerName: string): Plugin {
  const load = () => {
    const content = JSON.parse(
      readFileSync(resolve(process.cwd(), 'public/content.json'), 'utf8'),
    ) as SeoContent
    return buildSeo(content, ownerName)
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
      if (html.includes('application/ld+json')) return html
      const block = `    <script type="application/ld+json">\n${load().jsonld}\n    </script>\n`
      return html.replace('</head>', `${block}  </head>`)
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
  const media = (process.env.VITE_MEDIA_BASE_URL || env.VITE_MEDIA_BASE_URL || '').replace(
    /\/$/,
    '',
  )
  const ownerName = process.env.VITE_OWNER_NAME || env.VITE_OWNER_NAME || ''
  let origin = ''
  if (media && !media.startsWith('/')) {
    try {
      origin = new URL(media).origin
    } catch {
      origin = ''
    }
  }

  return {
    plugins: [
      react(),
      siteSeo(ownerName),
      {
        name: 'media-preconnect',
        transformIndexHtml(html: string) {
          if (!origin) return html
          const tag = `<link rel="preconnect" href="${origin}" />`
          if (html.includes(tag)) return html
          return html.replace('</head>', `    ${tag}\n  </head>`)
        },
      },
    ],
  }
})
