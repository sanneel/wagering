import { useEffect, useRef, useState } from 'react'

// Call on a ref: when the element enters the viewport, set seen=true (stays true).
// Useful for one-time entrance animations on scroll.
export function useInView(options = {}) {
  const ref = useRef(null)
  const [seen, setSeen] = useState(false)

  useEffect(() => {
    if (seen) return // Already triggered, no need to re-observe.

    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setSeen(true)
        observer.unobserve(entry.target)
      }
    }, options)

    if (ref.current) {
      observer.observe(ref.current)
    }

    return () => observer.disconnect()
  }, [seen, options])

  return [ref, seen]
}
