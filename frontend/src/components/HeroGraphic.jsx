// The landing page's hero graphic -- a placeholder, at explicit request,
// standing in for a real illustration later. Deliberately built from the
// app's OWN existing visual language rather than a generic stock motif
// (the earlier hero illustration was removed for being exactly that,
// "not good enough" -- see LandingPage.jsx's own prior comment): 5
// concentric rings colored via riskValueToCssColor, the SAME ramp the
// map's own risk surface and hazard-class legend already use (green,
// low risk, outermost -> red, high risk, innermost), with Logo.jsx's own
// river-bend glyph traced across the middle at large scale. Reads as
// "risk radiating outward from a point" -- literally what this app's
// own per-pixel composite score is -- not an arbitrary decoration.
import { riskValueToCssColor } from '../lib/colorRamp'

const RINGS = [0, 0.25, 0.5, 0.75, 1.0].map((v, i, arr) => ({
  radius: 96 - i * 18,
  color: riskValueToCssColor(v),
  // Outermost (lowest risk) ring drawn first/widest, so each
  // successive ring visually sits "in front of" (nearer the center
  // than) the one before it -- reversed here since the array above is
  // already ascending-risk, but rings should be drawn wide-to-narrow.
  delay: (arr.length - i) * 0.15,
}))

export default function HeroGraphic() {
  return (
    <div className="hero-graphic" aria-hidden="true">
      <svg viewBox="0 0 220 220" className="hero-graphic__svg">
        <defs>
          <filter id="heroGraphicGlow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <g transform="translate(110,110)" filter="url(#heroGraphicGlow)">
          {RINGS.map((ring) => (
            <circle
              key={ring.radius}
              r={ring.radius}
              fill="none"
              stroke={ring.color}
              strokeWidth={2.5}
              opacity={0.55}
              className="hero-graphic__ring"
              style={{ animationDelay: `${ring.delay}s` }}
            />
          ))}
          {/* Logo.jsx's own river-bend glyph, traced at hero scale --
              the same shape a viewer already saw small in the nav just
              above, not a second, unrelated motif. */}
          <path
            d="M-64 20c22-16 40-4 58-16s34-24 56-12"
            stroke="white"
            strokeWidth={3}
            strokeLinecap="round"
            fill="none"
            opacity={0.9}
          />
          <path
            d="M-64 2c24-12 42-2 62-12s28-14 48-8"
            stroke="var(--color-accent)"
            strokeWidth={2.4}
            strokeLinecap="round"
            fill="none"
            opacity={0.85}
          />
          <circle cx={62} cy={16} r={4} fill="white" />
        </g>
      </svg>
    </div>
  )
}
