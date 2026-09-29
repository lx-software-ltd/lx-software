const configured = (import.meta.env.VITE_MEDIA_BASE_URL ?? '').replace(/\/$/, '')

export const posterUrl = '/media/hk-harbour-v1-poster.webp'

export type RenditionHeight = 480 | 720

export function mediaOrigin(): string {
  if (!configured || configured.startsWith('/')) return ''
  try {
    return new URL(configured).origin
  } catch {
    return ''
  }
}

export function videoUrl(height: RenditionHeight, ext: 'mp4' | 'webm'): string {
  const file = `hk-harbour-v1-${height}.${ext}`
  return configured ? `${configured}/${file}` : `/media/${file}`
}

export function pickHeight(): RenditionHeight {
  if (typeof window === 'undefined') return 720
  return window.matchMedia('(max-width: 900px)').matches ? 480 : 720
}
