import { useEffect } from 'react'

const origin = 'https://www.lx-software.com'

export function usePageMeta(title: string, path: string, description: string) {
  useEffect(() => {
    document.title = title
    const canonical = document.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (canonical) canonical.href = `${origin}${path}`
    const meta = document.querySelector<HTMLMetaElement>('meta[name="description"]')
    if (meta) meta.content = description
  }, [title, path, description])
}
