import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const media = (process.env.VITE_MEDIA_BASE_URL || env.VITE_MEDIA_BASE_URL || '').replace(
    /\/$/,
    '',
  )
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
