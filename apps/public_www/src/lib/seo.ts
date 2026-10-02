import { useEffect } from 'react'
import { defaultSiteContent } from './content'

const origin = defaultSiteContent.site.url.replace(/\/$/, '')
const defaultRobots = 'index, follow, max-image-preview:large, max-snippet:-1'

export function usePageMeta(
  title: string,
  path: string,
  description: string,
  robots = defaultRobots,
) {
  useEffect(() => {
    document.title = title
    const canonical = document.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (canonical) canonical.href = `${origin}${path}`
    const meta = document.querySelector<HTMLMetaElement>('meta[name="description"]')
    if (meta) meta.content = description
    let robotsMeta = document.querySelector<HTMLMetaElement>('meta[name="robots"]')
    if (!robotsMeta) {
      robotsMeta = document.createElement('meta')
      robotsMeta.name = 'robots'
      document.head.appendChild(robotsMeta)
    }
    robotsMeta.content = robots
    return () => {
      robotsMeta.content = defaultRobots
    }
  }, [title, path, description, robots])
}
