// Drives the landing page's scroll-triggered "zoom in" reveal (see
// LandingPage.jsx) -- a section starts slightly scaled-down and
// transparent, then scales/fades up to its full size once it's
// substantially inside the viewport, and reverses if scrolled back out
// (a live relationship with scroll position, not a one-shot animation).
//
// Deliberately IntersectionObserver-driven rather than a continuous
// scroll-position scrub: universally supported (unlike CSS scroll-
// driven animations/`animation-timeline: view()`, Chromium-only as of
// this writing), no per-frame scroll-listener cost, and the actual
// motion is handled entirely by a CSS transition on a toggled class --
// this hook only ever decides true/false.
//
// The hero section (first on the page) gets its "zoomed" state for free
// with no special-casing: IntersectionObserver's callback fires
// immediately on `observe()` with whatever the current intersection
// state already is, and the hero is inside the viewport the instant the
// page loads.
import { useEffect, useRef, useState } from 'react'

export function useScrollZoom({ threshold = 0.35, rootMargin = '-10% 0px -10% 0px' } = {}) {
  const ref = useRef(null)
  const [active, setActive] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    // Accessibility: prefers-reduced-motion skips the observer entirely
    // and jumps straight to the fully-visible end state -- no motion, no
    // dependency on scroll position, content just there from the start.
    let reducedMotion = false
    try {
      reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    } catch {
      // matchMedia unavailable in some test/embed environments -- fall through to the animated path
    }
    if (reducedMotion) {
      setActive(true)
      return
    }

    const observer = new IntersectionObserver(([entry]) => setActive(entry.isIntersecting), {
      threshold,
      rootMargin,
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [threshold, rootMargin])

  return [ref, active]
}
