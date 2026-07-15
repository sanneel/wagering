import { useEffect, useRef, useState } from 'react'

// Scroll-scrubbed video hero (technique from oso95/scroll-world).
//
// The container is `heightVh` tall; a sticky full-viewport frame inside it
// holds the video. Scrolling through the container maps 0..1 progress onto
// the video timeline. The video is fetched as a blob so every frame is
// seekable without HTTP range support, and a rAF loop lerps toward the
// target time — issuing a seek only when the decoder is idle, so fast
// flicks can't pile up and freeze playback.
// `smoothing` is the per-frame lerp factor: lower = slower, floatier glide.
export default function ScrollVideo({
  src,
  heightVh = 300,
  smoothing = 0.18,
  children,
}) {
  const containerRef = useRef(null)
  const videoRef = useRef(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    let blobUrl = null
    let rafId = 0
    let cancelled = false
    let target = 0
    let cur = 0

    const reduceMotion = window.matchMedia(
      '(prefers-reduced-motion: reduce)'
    ).matches

    fetch(src)
      .then((r) => r.blob())
      .then((blob) => {
        if (cancelled) return
        blobUrl = URL.createObjectURL(blob)
        video.src = blobUrl
        video.load()
      })
      .catch(() => {
        // Leave the poster/fallback background; the page still works.
      })

    function onLoaded() {
      setReady(true)
      tick()
    }
    video.addEventListener('loadedmetadata', onLoaded)

    function readScroll() {
      const el = containerRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const scrollable = el.offsetHeight - window.innerHeight
      if (scrollable <= 0) return
      target = Math.min(1, Math.max(0, -rect.top / scrollable))
    }
    window.addEventListener('scroll', readScroll, { passive: true })
    readScroll()

    function tick() {
      if (cancelled) return
      // Lerp toward the scroll target; snap when reduced motion is preferred.
      cur += (target - cur) * (reduceMotion ? 1 : smoothing)
      const dur = video.duration
      if (dur && !video.seeking) {
        const t = Math.min(cur, 0.999) * dur
        if (Math.abs(video.currentTime - t) > 1 / 60) {
          video.currentTime = t
        }
      }
      rafId = requestAnimationFrame(tick)
    }

    return () => {
      cancelled = true
      cancelAnimationFrame(rafId)
      window.removeEventListener('scroll', readScroll)
      video.removeEventListener('loadedmetadata', onLoaded)
      if (blobUrl) URL.revokeObjectURL(blobUrl)
    }
  }, [src, smoothing])

  return (
    <div
      ref={containerRef}
      className="relative"
      style={{ height: `${heightVh}vh` }}
    >
      <div className="sticky top-0 h-screen w-full overflow-hidden bg-ink">
        <video
          ref={videoRef}
          muted
          playsInline
          preload="auto"
          className={`h-full w-full object-cover transition-opacity duration-700 ${ready ? 'opacity-100' : 'opacity-0'}`}
        />
        {children}
      </div>
    </div>
  )
}
