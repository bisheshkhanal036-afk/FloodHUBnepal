// The product's front door: a scroll-driven sequence of full-height
// sections -- hero (a CONTINUOUS scroll-scrubbed scale, growing to its
// own max size at the section's own scroll midpoint then shrinking back
// down, at explicit request -- see useHeroScrollScale.js), 4 methodology
// sections (one concept per screen, following inunda.ai's own "gold
// standard" scrollytelling pattern at explicit request: big centered
// typography, generous negative space, one idea per screen, rather than
// several cards crammed into one section), team, then data sources --
// these 4+2 animated via useScrollZoom.js's own binary IntersectionObserver-
// driven reveal instead (the hero is the one deliberate exception -- see
// useHeroScrollScale.js's own docstring for why), before the working
// tool (Sidebar + MapView). `onLaunch` is the only thing this needs from
// the outside, a callback that flips App.jsx's local view state to
// 'tool'. No app/AOI/overlay state lives here.
//
// Team and data sources are deliberately NOT rendered via the shared
// CreditsSection component AboutModal also uses -- that component's
// compact, all-in-one-grid layout is right for a modal popup, but wrong
// for a page section meant to "fill most of the screen"; this page
// builds its own larger, spacious markup directly from the same
// config/attribution.js data instead, so the two presentations can
// differ without one component trying to serve both.
//
// No academic citations anywhere on this page, at explicit request --
// not Saaty (1980), not Parajuli et al. (2023), not any of the per-
// criterion literature this app's own methodology draws on. Those
// citations still exist and are fully honored -- CreditsSection.jsx's
// own new "Methodology" group (rendered only in AboutModal, the in-tool
// "info" button) and config/literature.js's REFERENCES (surfaced via
// each criterion's own ⓘ LiteratureModal) are both still there in full.
// This page's own copy describes the SAME methods in the same
// substance, just without a paper trail attached to the sentence itself
// -- a front door, not a bibliography.
import { ADDITIONAL_SOURCE_CREDITS, SOURCE_ATTRIBUTIONS, TEAM_CREDITS } from '../config/attribution'
import { useHeroScrollScale } from '../lib/useHeroScrollScale'
import { useScrollZoom } from '../lib/useScrollZoom'
import HeroGraphic from './HeroGraphic'
import Logo from './Logo'

/**
 * One full-height, scroll-triggered "zoom in" panel -- see
 * useScrollZoom.js's own docstring for why this is IntersectionObserver-
 * driven rather than a continuous scroll-position scrub. Used by every
 * section on this page except the hero (HeroSection, below -- its own
 * continuous scroll-scrub instead, at explicit request).
 */
function ZoomSection({ id, className = '', children }) {
  const [ref, active] = useScrollZoom()
  return (
    <section
      id={id}
      ref={ref}
      className={`zoom-section ${className} ${active ? 'zoom-section--active' : ''}`}
    >
      <div className="zoom-section__inner">{children}</div>
    </section>
  )
}

/**
 * The hero, and ONLY the hero, uses a continuous scroll-scrubbed scale
 * (useHeroScrollScale) rather than ZoomSection's own binary reveal, at
 * explicit request -- everything inside it grows together as one group,
 * peaking at its own max size at the section's own scroll midpoint, then
 * shrinking back down approaching the next section, rather than jumping
 * straight to its final size the instant it's "in view enough" the way
 * every other section on this page still does.
 */
function HeroSection({ children }) {
  const [ref, scale] = useHeroScrollScale()
  return (
    <section className="zoom-section zoom-section--hero" ref={ref}>
      <div className="hero-scroll-scale" style={{ transform: `scale(${scale})` }}>
        {children}
      </div>
      <ScrollCue />
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

/** One full-screen methodology "scene" -- an eyebrow label, a heading, and body content, vertically centered. The shared shape all 4 methodology sections below use, so a 5th can be added later without inventing new markup. */
function MethodScene({ id, eyebrow, heading, children }) {
  return (
    <ZoomSection id={id} className="zoom-section--method-scene">
      <p className="method-scene__eyebrow">{eyebrow}</p>
      <h2 className="zoom-section__heading">{heading}</h2>
      <div className="method-scene__body">{children}</div>
    </ZoomSection>
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

      <HeroSection>
        <div className="hero hero--centered">
          <h1 className="hero__title">FloodHUB</h1>
          <p className="hero__tagline">Multi-criteria flood risk mapping for Nepal</p>

          <HeroGraphic />

          <p className="hero__description">
            Draw an area, select a hydrological basin, or select a district, weigh the physical and exposure
            factors that matter most through structured pairwise comparison, and generate a transparent, per-pixel
            risk surface built from elevation, slope, drainage, land cover, and built-environment data.
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
      </HeroSection>

      <MethodScene id="how-it-works" eyebrow="Step by step" heading="How to use it">
        <ol className="method-scene__steps">
          <li>
            <strong>Area of interest</strong> — draw a rectangle on the map, or select a hydrological basin or
            district instead.
          </li>
          <li>
            <strong>Criteria</strong> — check which physical and exposure factors to include: elevation, slope,
            drainage, land cover, rainfall, population, and more.
          </li>
          <li>
            <strong>Weighting</strong> — set each factor&rsquo;s relative importance via pairwise comparison, equal
            weights, or manual sliders.
          </li>
          <li>
            <strong>Compute</strong> — generates the per-pixel composite risk surface from your selections.
          </li>
          <li>
            <strong>Vulnerability report</strong> — hazard-class-tagged buildings, with per-class population and
            area statistics.
          </li>
        </ol>
      </MethodScene>

      <MethodScene id="what-is-ahp" eyebrow="The weighting method" heading="What is AHP?">
        <p className="method-scene__text">
          FloodHUB weighs flood risk using the Analytic Hierarchy Process (AHP) — a structured way to turn expert
          judgment into numbers instead of a hidden formula. Each conditioning factor is reprojected onto a common
          10&nbsp;m grid, reclassified into five ordinal risk classes, and combined as a weighted sum, where the
          weights come from your own pairwise comparisons and are checked for logical consistency before they&rsquo;re
          ever used.
        </p>
      </MethodScene>

      <MethodScene id="the-clusters" eyebrow="Five clusters, one score" heading="The method">
        <p className="method-scene__text">
          Every criterion is grouped into one of five canonical clusters — Topographic, Hydrological, Land Use,
          Infrastructure, and Exposure. Each cluster&rsquo;s own weight, and each criterion&rsquo;s weight within it,
          come from your own pairwise comparisons, not a fixed, hidden formula — the same weighted-sum math is
          shown openly at every step.
        </p>
      </MethodScene>

      <MethodScene id="meteor-distinction" eyebrow="One dataset, two roles" heading="Criterion vs. validation">
        <p className="method-scene__text">
          METEOR&rsquo;s modeled flood hazard maps can be used two different ways here, and they are not the same
          thing. As a <strong>criterion</strong>, METEOR&rsquo;s modeled water depth becomes one weighted input
          blended into your own composite score, alongside terrain, land cover, rainfall, and exposure. As{' '}
          <strong>validation</strong>, the same data is shown as a live, independent overlay directly on the map —
          never blended into your score — so you can visually sanity-check your own computed risk surface against a
          third party&rsquo;s model, since METEOR is itself a modeled estimate, not ground truth.
        </p>
      </MethodScene>

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
        <p className="zoom-section__footnote">
          Full methodology citations are available from the <strong>ⓘ</strong> info button inside the tool.
        </p>
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
