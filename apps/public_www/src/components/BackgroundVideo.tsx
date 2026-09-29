import { useEffect, useRef, useState, type SyntheticEvent } from 'react'
import { pickHeight, posterUrl, videoSources, type RenditionHeight } from '../lib/media'

export function BackgroundVideo({ still }: { still: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [failed, setFailed] = useState(false)
  const [height] = useState<RenditionHeight>(pickHeight)

  useEffect(() => {
    const video = videoRef.current
    if (!video || still || failed) return
    const onVisibility = () => {
      if (document.hidden) {
        video.pause()
        return
      }
      void video.play().catch(() => setFailed(true))
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
        ref={videoRef}
        autoPlay
        muted
        loop
        playsInline
        poster={posterUrl}
        preload={height === 480 ? 'metadata' : 'auto'}
        disablePictureInPicture
        disableRemotePlayback
        onError={() => setFailed(true)}
        onCanPlay={(event) => {
          void event.currentTarget.play().catch(() => setFailed(true))
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
