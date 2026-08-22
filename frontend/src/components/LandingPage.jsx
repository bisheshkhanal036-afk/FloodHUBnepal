// The product's front door: hero (identity + one-line pitch + launch
// CTA) followed by a dedicated Credits section, shown before the
// working tool (Sidebar + MapView) rather than dropping the user
// straight into it. Purely presentational -- `onLaunch` is the only
// thing it needs from the outside, a callback that flips App.jsx's
// local view state to 'tool'. No app/AOI/overlay state lives here.
//
// No hero illustration -- an earlier version had an inline-SVG contour
// motif here, removed at the user's request ("not good enough"). The
// hero now leans on typography, the Logo mark, and a plain background
// wash instead of a standalone graphic.
import CreditsSection from './CreditsSection'
import Logo from './Logo'

export default function LandingPage({ onLaunch }) {
  return (
    <div className="landing">
      <header className="landing__nav">
        <div className="landing__brand">
          <Logo size={28} />
          FloodHUB
        </div>
        <button type="button" className="button button--ghost" onClick={onLaunch}>
          Launch tool →
        </button>
      </header>

      <section className="hero hero--centered">
        <div className="hero__content">
          <p className="hero__eyebrow">Multi-criteria flood risk mapping</p>
          <h1 className="hero__title">FloodHUB</h1>
          <p className="hero__description">
            An AHP-based multi-criteria flood risk mapping platform. Draw an area or select a hydrological basin,
            weigh the physical and exposure factors that matter most through Saaty&rsquo;s Analytic Hierarchy Process,
            and generate a transparent, per-pixel risk surface built from elevation, slope, drainage, land cover, and
            built-environment data — currently piloted for the Kathmandu Valley.
          </p>
          <div className="hero__actions">
            <button type="button" className="button button--primary button--lg" onClick={onLaunch}>
              Launch tool
            </button>
            <a className="button button--text" href="#credits">
              About &amp; credits
            </a>
          </div>
          <ul className="hero__facts">
            <li>Basin-aware AOI selection</li>
            <li>AHP · equal · manual weighting</li>
            <li>Day &amp; night basemaps</li>
          </ul>
        </div>
      </section>

      <section className="landing__credits" id="credits">
        <h2 className="landing__credits-heading">Credits</h2>
        <p className="landing__credits-sub">The people and data behind this tool.</p>
        <CreditsSection variant="page" />
      </section>

      <footer className="landing__footer">
        <span>FloodHUB — Kathmandu Valley pilot</span>
        <button type="button" className="link-button" onClick={onLaunch}>
          Launch tool →
        </button>
      </footer>
    </div>
  )
}
