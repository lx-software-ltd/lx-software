import { readFileSync } from 'node:fs'
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { build as viteBuild, defineConfig, loadEnv, type Plugin, type ResolvedConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { deferStylesheetLinks, fontPreloadTags } from './scripts/index-html.ts'
import {
  applyRouteHead,
  assertInlineSafe,
  injectAppHtml,
  inlineStylesheets,
  routeOutputPaths,
} from './scripts/prerender.ts'
import { applyHead, buildSeo, type SeoFiles, type SeoOptions } from './scripts/site-seo.ts'
import { defaultSiteContent } from './src/lib/content.ts'
import { mediaOrigin } from './src/lib/media.ts'

/**
 * After the browser build, renders every route to static HTML so crawlers
 * that do not run JavaScript (Bing, link previews, most LLM fetchers) see
 * the page body, and Google indexes on the first pass. `main.tsx` hydrates
 * the markup. Set `PUBLIC_WWW_PRERENDER=0` to skip it.
 */
function prerenderPages(getSeo: () => SeoFiles): Plugin {
  let config: ResolvedConfig
  return {
    name: 'prerender-pages',
    apply: 'build',
    configResolved(resolved) {
      config = resolved
    },
    async closeBundle() {
      if (config.build.ssr || process.env.PUBLIC_WWW_PRERENDER === '0') return
      const outDir = resolve(config.root, config.build.outDir)
      const ssrDir = join(outDir, '.ssr')
      await viteBuild({
        configFile: false,
        root: config.root,
        mode: config.mode,
        logLevel: 'warn',
        plugins: [react()],
        build: {
          ssr: 'src/entry-server.tsx',
          outDir: ssrDir,
          emptyOutDir: true,
          copyPublicDir: false,
          rollupOptions: { output: { entryFileNames: 'entry-server.js' } },
        },
      })
      try {
        const entry = (await import(pathToFileURL(join(ssrDir, 'entry-server.js')).href)) as {
          render: (url: string) => Promise<string>
        }
        const template = await readFile(join(outDir, 'index.html'), 'utf8')
        const cssCache = new Map<string, string>()
        const readCss = (href: string) => {
          let css = cssCache.get(href)
          if (css === undefined) {
            css = readFileSync(join(outDir, href.replace(/^\//, '')), 'utf8')
            assertInlineSafe(css, href)
            cssCache.set(href, css)
          }
          return css
        }
        for (const route of getSeo().routes) {
          const appHtml = await entry.render(route.path)
          if (!appHtml.includes('<h1')) throw new Error(`pre-render of ${route.path} produced no <h1>`)
          let html = applyRouteHead(template, route.head, route.jsonld)
          html = injectAppHtml(html, appHtml)
          const inlined = inlineStylesheets(html, readCss)
          if (inlined.inlined.length === 0) throw new Error('no deferred stylesheet found to inline')
          const outputs = routeOutputPaths(route.path)
          for (const relative of outputs) {
            const file = join(outDir, relative)
            await mkdir(dirname(file), { recursive: true })
            await writeFile(file, inlined.html)
          }
          config.logger.info(`pre-rendered ${route.path} -> ${outputs.join(', ')}`)
        }
      } finally {
        await rm(ssrDir, { recursive: true, force: true })
      }
    },
  }
}

function seoLoader(options: SeoOptions): () => SeoFiles {
  let files: SeoFiles | undefined
  return () => {
    files ??= buildSeo(defaultSiteContent, options)
    return files
  }
}

function siteSeo(load: () => SeoFiles): Plugin {
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
  const seo = seoLoader({ linkedin })

  return {
    plugins: [
      react(),
      siteSeo(seo),
      prerenderPages(seo),
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
