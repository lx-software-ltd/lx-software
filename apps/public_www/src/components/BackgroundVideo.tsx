import { useEffect, useRef, useState, type SyntheticEvent } from 'react'
import { pickHeight, posterUrl, videoSources, type RenditionHeight } from '../lib/media'

export function BackgroundVideo({ still }: { still: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [failed, setFailed] = useState(false)
  const [height] = useState<RenditionHeight>(pickHeight)

  const bindVideo = (node: HTMLVideoElement | null) => {
    videoRef.current = node
    if (!node) return
    // React's video typings omit defaultMuted. Set the DOM property so iOS
    // treats the element as muted before the first autoplay attempt.
    node.defaultMuted = true
    node.muted = true
  }

  useEffect(() => {
    const video = videoRef.current
    if (!video || still || failed) return
    video.defaultMuted = true
    video.muted = true
    const tryPlay = () => {
      void video.play().catch(() => {
        // iPad rejects play() while a source is still switching. Leave the
        // element in place so the next canplay can start it.
      })
    }
    tryPlay()
    const onVisibility = () => {
      if (document.hidden) {
        video.pause()
        return
      }
      tryPlay()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [still, failed])

  if (still || failed) {
    return (
      <div className="bg-video" aria-hidden="true">
        <img src={posterUrl} alt="" width={1280} height={720} fetchPriority="high" />
      </div>
    )
  }

  const sources = videoSources(height)
  const failIfExhausted = (event: SyntheticEvent<HTMLSourceElement>) => {
    const video = event.currentTarget.parentElement
    if (!(video instanceof HTMLVideoElement)) return
    const listed = video.querySelectorAll('source')
    if (listed[listed.length - 1] === event.currentTarget) setFailed(true)
  }
  return (
    <div className="bg-video" aria-hidden="true">
      <video
        ref={bindVideo}
        autoPlay
        muted
        loop
        playsInline
        poster={posterUrl}
        preload={height === 480 ? 'metadata' : 'auto'}
        disablePictureInPicture
        disableRemotePlayback
        onCanPlay={(event) => {
          const video = event.currentTarget
          video.muted = true
          void video.play().catch(() => undefined)
        }}
      >
        {sources.map((source) => (
          <source key={source.type} src={source.src} type={source.type} onError={failIfExhausted} />
        ))}
        <img src={posterUrl} alt="" />
      </video>
    </div>
  )
}
