export const posterUrl = '/media/hk-harbour-v1-poster.webp'

export type RenditionHeight = 480 | 720

function mediaBase(configured?: string): string {
  const value = configured ?? import.meta.env.VITE_MEDIA_BASE_URL ?? ''
  return value.replace(/\/$/, '')
}

/** Origin of the media host, or '' when files are served from this site. */
export function mediaOrigin(configured?: string): string {
  const base = mediaBase(configured)
  if (!base || base.startsWith('/')) return ''
  try {
    return new URL(base).origin
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

/** Runs `task` after load, on an idle slice, so the harbour file stays off the first paint. */
export function afterFirstPaint(task: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined

  let cancelled = false
  let idleHandle = 0
  let timerHandle = 0

  const run = () => {
    if (cancelled) return
    if (typeof window.requestIdleCallback === 'function') {
      idleHandle = window.requestIdleCallback(
        () => {
          if (!cancelled) task()
        },
        { timeout: 1500 },
      )
      return
    }
    timerHandle = window.setTimeout(() => {
      if (!cancelled) task()
    }, 1)
  }

  if (document.readyState === 'complete') run()
  else window.addEventListener('load', run, { once: true })

  return () => {
    cancelled = true
    window.removeEventListener('load', run)
    if (idleHandle) window.cancelIdleCallback(idleHandle)
    if (timerHandle) window.clearTimeout(timerHandle)
  }
}
