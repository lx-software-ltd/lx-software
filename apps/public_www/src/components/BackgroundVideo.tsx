import { useEffect, useState } from 'react'
import flagUrl from '../assets/hk-flag.png'
import { trackEvent } from '../lib/analytics'
import { BOAT_FLAG, boatFlagAtTime } from '../lib/boatFlag'
import { afterFirstPaint, pickHeight, videoSources, type RenditionHeight } from '../lib/media'

function element<T extends HTMLElement>(id: string, kind: { new (): T }): T | null {
  const node = document.getElementById(id)
  return node instanceof kind ? node : null
}

export function BackgroundVideo({ still }: { still: boolean }) {
  const [failed, setFailed] = useState(false)
  const [height] = useState<RenditionHeight>(pickHeight)

  useEffect(() => {
    const video = element('bg-video-el', HTMLVideoElement)
    const frame = element('bg-video-frame', HTMLDivElement)
    if (!video || !frame) return

    // React's video typings omit defaultMuted. Set the DOM property so iOS
    // treats the element as muted before the first autoplay attempt.
    video.defaultMuted = true
    video.muted = true

    const clearSources = () => {
      video.querySelectorAll('source').forEach((source) => source.remove())
      video.removeAttribute('src')
    }

    if (still || failed) {
      video.pause()
      clearSources()
      return
    }

    let cancelled = false
    const tryPlay = () => {
      if (cancelled) return
      video.defaultMuted = true
      video.muted = true
      void video.play().catch(() => undefined)
    }
    const onCanPlay = () => tryPlay()
    const onVisibility = () => {
      if (document.hidden) {
        video.pause()
        return
      }
      tryPlay()
    }
    const onMeta = () => {
      if (video.videoWidth > 0) {
        frame.style.setProperty('--video-aspect', String(video.videoWidth / video.videoHeight))
      }
    }

    const attach = () => {
      if (cancelled || video.querySelector('source')) return
      const sources = videoSources(height)
      sources.forEach((source, index) => {
        const el = document.createElement('source')
        el.src = source.src
        el.type = source.type
        if (index === sources.length - 1) {
          el.addEventListener('error', () => {
            if (cancelled) return
            setFailed(true)
            trackEvent({ event: 'media_error', source: el.src })
          })
        }
        video.appendChild(el)
      })
      video.addEventListener('loadedmetadata', onMeta)
      video.addEventListener('canplay', onCanPlay)
      video.load()
      if (video.videoWidth > 0) onMeta()
      tryPlay()
    }

    const cancelIdle = afterFirstPaint(attach)
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      cancelled = true
      cancelIdle()
      video.removeEventListener('loadedmetadata', onMeta)
      video.removeEventListener('canplay', onCanPlay)
      document.removeEventListener('visibilitychange', onVisibility)
      video.pause()
      clearSources()
    }
  }, [still, failed, height])

  useEffect(() => {
    const video = element('bg-video-el', HTMLVideoElement)
    const frame = element('bg-video-frame', HTMLDivElement)
    const flag = element('boat-flag', HTMLDivElement)
    if (!video || !frame || !flag) return

    flag.style.backgroundImage = `url("${flagUrl}")`
    if (still || failed) {
      flag.hidden = true
      return
    }

    let frameWidth = frame.clientWidth
    let frameHeight = frame.clientHeight
    let lastFrame = -1
    let lastPaint = ''

    const place = () => {
      const box = boatFlagAtTime(video.currentTime)
      if (!box || frameWidth === 0 || frameHeight === 0) {
        flag.hidden = true
        lastPaint = ''
        return
      }
      const width = (box.width / BOAT_FLAG.videoWidth) * frameWidth
      const heightPx = (box.height / BOAT_FLAG.videoHeight) * frameHeight
      const transform = `translate(${(box.x / BOAT_FLAG.videoWidth) * frameWidth}px, ${(box.y / BOAT_FLAG.videoHeight) * frameHeight}px)`
      const paint = `${width}|${heightPx}|${transform}`
      if (paint === lastPaint && !flag.hidden) return
      lastPaint = paint
      flag.hidden = false
      flag.style.width = `${width}px`
      flag.style.height = `${heightPx}px`
      flag.style.transform = transform
    }

    const onMeta = () => {
      if (video.videoWidth > 0) {
        frame.style.setProperty('--video-aspect', String(video.videoWidth / video.videoHeight))
      }
      lastFrame = -1
      place()
    }
    video.addEventListener('loadedmetadata', onMeta)
    if (video.videoWidth > 0) onMeta()

    const resize = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (!rect) return
      frameWidth = rect.width
      frameHeight = rect.height
      lastFrame = -1
      place()
    })
    resize.observe(frame)

    let vfc = 0
    let raf = 0
    const draw = () => {
      if (document.hidden) return
      const frameIndex = Math.round(video.currentTime * BOAT_FLAG.fps)
      if (frameIndex === lastFrame) return
      lastFrame = frameIndex
      place()
    }
    if (typeof video.requestVideoFrameCallback === 'function') {
      const onFrame: VideoFrameRequestCallback = () => {
        draw()
        vfc = video.requestVideoFrameCallback(onFrame)
      }
      vfc = video.requestVideoFrameCallback(onFrame)
    } else {
      const tick = () => {
        draw()
        raf = requestAnimationFrame(tick)
      }
      raf = requestAnimationFrame(tick)
    }

    return () => {
      video.removeEventListener('loadedmetadata', onMeta)
      resize.disconnect()
      if (vfc) video.cancelVideoFrameCallback(vfc)
      if (raf) cancelAnimationFrame(raf)
      flag.hidden = true
    }
  }, [still, failed])

  return null
}
