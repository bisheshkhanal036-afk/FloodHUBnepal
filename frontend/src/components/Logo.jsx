// Small reusable mark used in both LandingPage's nav and Sidebar's
// header -- a rounded badge with a simplified two-contour-line + river-
// bend glyph (the same visual idea the old hero illustration went for,
// distilled down to something legible at 28-40px instead of a flat
// gradient square). Purely decorative, no props needed beyond sizing via
// the wrapping className.
export default function Logo({ size = 32 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Logo"
    >
      <defs>
        <linearGradient id="logoBg" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="var(--color-primary)" />
          <stop offset="100%" stopColor="var(--color-primary-hover)" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#logoBg)" />
      <path
        d="M6 20c3-3 5-1 8-3s5-4 8-2"
        stroke="var(--color-accent)"
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
        opacity="0.95"
      />
      <path
        d="M6 14.5c3.5-2.5 6-1 9-2.5s4-2.5 7-1.5"
        stroke="white"
        strokeWidth="1.6"
        strokeLinecap="round"
        fill="none"
        opacity="0.85"
      />
      <circle cx="23" cy="21.5" r="1.6" fill="white" />
    </svg>
  )
}
