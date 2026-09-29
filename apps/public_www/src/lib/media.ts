export const posterUrl = '/media/hk-harbour-v1-poster.webp'

/** Native harbour clip size. Site content shares this max width. */
export const VIDEO_WIDTH = 1280
export const VIDEO_HEIGHT = 720

export type RenditionHeight = 480 | 720

function mediaBase(): string {
  return (import.meta.env.VITE_MEDIA_BASE_URL ?? '').replace(/\/$/, '')
}

export function mediaOrigin(): string {
  const configured = mediaBase()
  if (!configured || configured.startsWith('/')) return ''
  try {
    return new URL(configured).origin
  } catch {
    return ''
  }
}

export function videoUrl(height: RenditionHeight, ext: 'mp4' | 'webm'): string {
  const file = `hk-harbour-v1-${height}.${ext}`
  const configured = mediaBase()
  return configured ? `${configured}/${file}` : `/media/${file}`
}

/** iPadOS reports a desktop Macintosh UA. Touch points distinguish it. */
export function isAppleTouch(): boolean {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent
  if (/iPad|iPhone|iPod/.test(ua)) return true
  return navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1
}

/** Narrow screens and iPad skip AV1. Safari treats a failed WebM source as a dead video. */
export function videoSources(height: RenditionHeight): { src: string; type: string }[] {
  const mp4 = { src: videoUrl(height, 'mp4'), type: 'video/mp4' }
  if (height === 480 || isAppleTouch()) return [mp4]
  return [{ src: videoUrl(height, 'webm'), type: 'video/webm; codecs=av01.0.05M.08' }, mp4]
}

export function pickHeight(): RenditionHeight {
  if (typeof window === 'undefined') return 720
  return window.matchMedia('(max-width: 900px)').matches ? 480 : 720
}
