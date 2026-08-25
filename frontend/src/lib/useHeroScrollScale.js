// Drives the hero section's own scroll-scrubbed scale, at explicit
// request: unlike every other landing-page section (useScrollZoom.js's
// own binary "in view or not" reveal), the hero should continuously grow
// as the page is scrolled through it, peak at its own MAX size at the
// section's own scroll midpoint, then shrink back down as the next
// section (the first methodology scene) is approached -- a live,
// per-frame relationship with scroll position, not a one-shot reveal.
//
// A real scroll listener, not IntersectionObserver -- continuous scrub
// genuinely needs the actual scroll offset every frame, which
// IntersectionObserver's own threshold buckets can only coarsely
// approximate (see useScrollZoom.js's own docstring for why THAT hook
// avoids a scroll listener; this is the one place on the page a
// continuous value is actually the point, not an optimization to avoid).
// Throttled to one recompute per animation frame (never per raw scroll
// event) to keep it cheap -- this is the only scroll listener on the
// page, not a pattern repeated per-section.
import { useEffect, useRef, useState } from 'react'

const MIN_SCALE = 0.86
const MAX_SCALE = 1.0

export function useHeroScrollScale() {
  const ref = useRef(null)
  const [scale, setScale] = useState(MAX_SCALE)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    let reducedMotion = false
    try {
      reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    } catch {
      // matchMedia unavailable in some test/embed environments -- fall through to the animated path
    }
    if (reducedMotion) {
      setScale(MAX_SCALE)
      return
    }

    let ticking = false
    function update() {
      ticking = false
      const rect = el.getBoundingClientRect()
      const sectionHeight = rect.height || window.innerHeight
      // progress: 0 when the section's own top is at the viewport top
      // (the very start of scrolling through it), 1 a full section-
      // height later (the section has entirely scrolled past) --
      // clamped, so it holds steady at either end rather than
      // overshooting the sine curve below past its own peak.
      const progress = Math.min(1, Math.max(0, -rect.top / sectionHeight))
      // sin(0) = 0, sin(pi/2) = 1 (at progress 0.5, the section's own
      // scroll midpoint), sin(pi) = 0 -- a smooth grow-then-shrink arc
      // peaking exactly mid-scroll, not a linear ramp that would peak
      // only at one edge.
      const eased = Math.sin(progress * Math.PI)
      setScale(MIN_SCALE + (MAX_SCALE - MIN_SCALE) * eased)
    }

    function onScroll() {
      if (ticking) return
      ticking = true
      requestAnimationFrame(update)
    }

    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [])

  return [ref, scale]
}
