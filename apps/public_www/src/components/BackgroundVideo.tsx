import { useEffect, useRef, useState } from 'react'
import { pickHeight, posterUrl, videoUrl, type RenditionHeight } from '../lib/media'

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

  const narrow = height === 480
  return (
    <div className="bg-video" aria-hidden="true">
      <video
        ref={videoRef}
        autoPlay
        muted
        loop
        playsInline
        poster={posterUrl}
        preload={narrow ? 'metadata' : 'auto'}
        disablePictureInPicture
        disableRemotePlayback
        onError={() => setFailed(true)}
        onCanPlay={(event) => {
          void event.currentTarget.play().catch(() => setFailed(true))
        }}
      >
        <source src={videoUrl(height, 'webm')} type="video/webm; codecs=av01.0.05M.08" />
        <source src={videoUrl(height, 'mp4')} type="video/mp4" />
        <img src={posterUrl} alt="" />
      </video>
    </div>
  )
}
