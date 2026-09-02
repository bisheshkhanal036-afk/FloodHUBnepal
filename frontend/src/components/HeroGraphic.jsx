// The landing page's hero graphic -- the project's real icon artwork
// (the shield + river-bend mark, same image Logo.jsx and the browser
// favicon use -- see public/icon.png), shown on its own at large scale.
// Replaces an earlier placeholder (first a hand-drawn river-path glyph,
// then that glyph overlaid on a ring of risk-ramp circles) now that
// real icon artwork exists and doesn't need dressing up further.
export default function HeroGraphic() {
  return (
    <div className="hero-graphic" aria-hidden="true">
      {/* Same file Logo.jsx/index.html's favicon use -- served from
          public/, not bundled a second time through an import. */}
      <img src="/icon.png" alt="" className="hero-graphic__icon" />
    </div>
  )
}
