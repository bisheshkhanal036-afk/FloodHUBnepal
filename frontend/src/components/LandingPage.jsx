// The product's front door: a scroll-driven sequence of three full-height
// sections -- hero (zoomed in immediately, no scroll needed), team
// (zoomed in to fill most of the screen as it's scrolled to, exactly
// three members), then data sources (zoomed in last) -- each animated
// via useScrollZoom.js's IntersectionObserver-driven reveal, before the
// working tool (Sidebar + MapView). `onLaunch` is the only thing this
// needs from the outside, a callback that flips App.jsx's local view
// state to 'tool'. No app/AOI/overlay state lives here.
//
// Team and data sources are deliberately NOT rendered via the shared
// CreditsSection component AboutModal also uses -- that component's
// compact, all-in-one-grid layout is right for a modal popup, but wrong
// for a page section meant to "fill most of the screen"; this page
// builds its own larger, spacious markup directly from the same
// config/attribution.js data instead, so the two presentations can
// differ without one component trying to serve both.
//
// No hero illustration -- an earlier version had an inline-SVG contour
// motif here, removed at the user's request ("not good enough"). The
// hero now leans on typography, the Logo mark, and a plain background
// wash instead of a standalone graphic.
import { ADDITIONAL_SOURCE_CREDITS, SOURCE_ATTRIBUTIONS, TEAM_CREDITS } from '../config/attribution'
// METHOD_INTRO's own AHP paragraph is reused verbatim here (not
// re-written) -- the same "one place holds the real text, everything
// else quotes it" discipline this project already applies to
// SOURCE_ATTRIBUTIONS (config/attribution.js's own comment: "copied
// VERBATIM from backend/app/data/attribution.py's own constants").
// Keeps the landing page's "What is AHP?" card and the in-tool
// LiteratureModal's method intro from ever silently drifting apart.
import { METHOD_INTRO } from '../config/literature'
import { useScrollZoom } from '../lib/useScrollZoom'
import Logo from './Logo'

/**
 * One full-height, scroll-triggered "zoom in" panel -- see
 * useScrollZoom.js's own docstring for why this is IntersectionObserver-
 * driven rather than a continuous scroll-position scrub.
 *
 * `overlay` (optional) renders as a plain sibling of the scaled/faded
 * `.zoom-section__inner` -- inside the full-height `<section>` for
 * positioning purposes (e.g. pinned to its bottom edge), but outside the
 * zoom transform/fade itself, for content that shouldn't visually scale
 * with the reveal (the hero's own scroll-down cue).
 */
function ZoomSection({ id, className = '', overlay = null, children }) {
  const [ref, active] = useScrollZoom()
  return (
    <section
      id={id}
      ref={ref}
      className={`zoom-section ${className} ${active ? 'zoom-section--active' : ''}`}
    >
      <div className="zoom-section__inner">{children}</div>
      {overlay}
    </section>
  )
}

/** A cascading "wave" of 3 chevrons, fading in and out in sequence, hinting there's more to scroll to. Purely decorative (aria-hidden) -- the page works identically without it. */
function ScrollCue() {
  return (
    <div className="hero__scroll-cue" aria-hidden="true">
      <span className="hero__scroll-chevron" />
      <span className="hero__scroll-chevron" />
      <span className="hero__scroll-chevron" />
    </div>
  )
}

export default function LandingPage({ onLaunch }) {
  const allSources = [...SOURCE_ATTRIBUTIONS, ...ADDITIONAL_SOURCE_CREDITS]

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

      <ZoomSection className="zoom-section--hero" overlay={<ScrollCue />}>
        <div className="hero hero--centered">
          <p className="hero__eyebrow">Multi-criteria flood risk mapping</p>
          <h1 className="hero__title">FloodHUB</h1>
          <p className="hero__description">
            An AHP-based multi-criteria flood risk mapping platform for Nepal. Draw an area, select a hydrological
            basin, or select a district, weigh the physical and exposure factors that matter most through
            Saaty&rsquo;s Analytic Hierarchy Process, and generate a transparent, per-pixel risk surface built from
            elevation, slope, drainage, land cover, and built-environment data.
          </p>
          <div className="hero__actions">
            <button type="button" className="button button--primary button--lg" onClick={onLaunch}>
              Launch tool
            </button>
            <a className="button button--text" href="#team">
              About &amp; credits
            </a>
          </div>
          <ul className="hero__facts">
            <li>Basin-aware AOI selection</li>
            <li>AHP · equal · manual weighting</li>
            <li>Day &amp; night basemaps</li>
          </ul>
        </div>
      </ZoomSection>

      <ZoomSection id="how-it-works" className="zoom-section--method">
        <h2 className="zoom-section__heading">How it works</h2>
        <p className="zoom-section__sub">The method behind the map, and how to drive it.</p>
        <div className="method-showcase">
          <div className="method-showcase__card">
            <h3 className="method-showcase__title">How to use</h3>
            <ol className="method-showcase__steps">
              <li>
                <strong>Area of interest</strong> — draw a rectangle on the map, or select a hydrological basin or
                district instead.
              </li>
              <li>
                <strong>Criteria</strong> — check which physical and exposure factors to include: elevation,
                slope, drainage, land cover, rainfall, population, and more.
              </li>
              <li>
                <strong>Weighting</strong> — set each factor&rsquo;s relative importance via AHP pairwise
                comparison, equal weights, or manual sliders.
              </li>
              <li>
                <strong>Compute</strong> — generates the per-pixel composite risk surface from your selections.
              </li>
              <li>
                <strong>Vulnerability report</strong> — hazard-class-tagged buildings, with per-class population
                and area statistics.
              </li>
            </ol>
          </div>

          <div className="method-showcase__card">
            <h3 className="method-showcase__title">What is AHP?</h3>
            <p className="method-showcase__text">{METHOD_INTRO.body[0]}</p>
          </div>

          <div className="method-showcase__card">
            <h3 className="method-showcase__title">The method</h3>
            <p className="method-showcase__text">
              Every criterion is grouped into one of five canonical clusters — Topographic, Hydrological, Land
              Use, Infrastructure, and Exposure — following the AHP flood-susceptibility approach of Parajuli et
              al. (2023). Each cluster&rsquo;s own weight, and each criterion&rsquo;s weight within it, come from
              your own pairwise comparisons, not a fixed, hidden formula — the same weighted-sum math is shown
              openly at every step.
            </p>
          </div>

          <div className="method-showcase__card">
            <h3 className="method-showcase__title">METEOR: criterion vs. validation</h3>
            <p className="method-showcase__text">
              METEOR&rsquo;s modeled flood hazard maps can be used two different ways here, and they are not the
              same thing. As a <strong>criterion</strong>, METEOR&rsquo;s modeled water depth becomes one weighted
              input blended into your own composite AHP score, alongside terrain, land cover, rainfall, and
              exposure. As <strong>validation</strong>, the same data is shown as a live, independent overlay
              directly on the map — never blended into your score — so you can visually sanity-check your own
              computed risk surface against a third party&rsquo;s model, since METEOR is itself a modeled
              estimate (the Fathom framework), not ground truth.
            </p>
          </div>
        </div>
      </ZoomSection>

      <ZoomSection id="team" className="zoom-section--team">
        <h2 className="zoom-section__heading">The team</h2>
        <p className="zoom-section__sub">Three people built this tool.</p>
        <div className="team-showcase">
          {TEAM_CREDITS.map((person) => (
            <div className="team-showcase__card" key={person.id}>
              {person.photo ? (
                <img className="team-showcase__photo" src={person.photo} alt={person.name} />
              ) : (
                <div className="team-showcase__avatar" aria-hidden="true">
                  {person.name.charAt(0)}
                </div>
              )}
              <div className="team-showcase__name">{person.name}</div>
              <a className="team-showcase__email" href={`mailto:${person.email}`}>
                {person.email}
              </a>
              {person.linkedin && (
                <a className="team-showcase__linkedin" href={person.linkedin} target="_blank" rel="noreferrer">
                  LinkedIn ↗
                </a>
              )}
            </div>
          ))}
        </div>
      </ZoomSection>

      <ZoomSection id="sources" className="zoom-section--sources">
        <h2 className="zoom-section__heading">Data sources</h2>
        <p className="zoom-section__sub">Every dataset this tool reads from, credited in full.</p>
        <div className="source-showcase">
          {allSources.map((s) => (
            <div className="source-showcase__card" key={s.id}>
              <div className="source-showcase__name">{s.name}</div>
              <p className="source-showcase__text">{s.text}</p>
            </div>
          ))}
        </div>
      </ZoomSection>

      <footer className="landing__footer">
        <span>FloodHUB — Nepal</span>
        <button type="button" className="link-button" onClick={onLaunch}>
          Launch tool →
        </button>
      </footer>
    </div>
  )
}
