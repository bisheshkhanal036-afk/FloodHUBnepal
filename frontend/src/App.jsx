// One cohesive page: sidebar (AOI -> criteria -> weighting -> compute ->
// result) beside the map, both driven by the same AppStateContext. See
// src/state/AppStateContext.jsx for the shared state shape this whole
// tree reads/writes, and each component's own module docstring for its
// specific responsibility -- structured this way (context + small
// single-purpose components) specifically so a later phase
// (vulnerability classification, shelter markers) can extend this page
// rather than replace it.
//
// `view` ('landing' | 'modes' | 'citizen' | 'tool') is local,
// presentation-only navigation
// state -- which page is showing, nothing about the AOI/criteria/AHP/
// overlay data flow, which stays entirely inside AppStateProvider
// exactly as before. AppStateProvider wraps both views (not just
// 'tool') so app state is never torn down/reset by switching back to
// the landing page and launching again.
//
// Code-split: Sidebar/ReportOverlay/DataGapNotice/MeteorFloodLegend
// (plain React components, no imperative native/WebGL side effects of
// their own) are lazy-loaded, not imported eagerly at the top of this
// file -- a first-time visitor lands on LandingPage, which needs none
// of them, so importing them unconditionally here meant every landing-
// page visit paid for that code up front.
//
// MapView and CitizenView are deliberately kept as ORDINARY eager
// imports, not lazy -- a real regression, found and reverted: both
// construct a `new maplibregl.Map(...)` (a real WebGL context) inside a
// `useEffect`, and this app's `main.jsx` wraps everything in
// `<React.StrictMode>`, which intentionally double-invokes every
// effect in development specifically to catch cleanup bugs. Wrapping a
// component that does heavy imperative WebGL setup in `React.lazy` +
// `Suspense` changes exactly when/how many times that double-invoke
// happens relative to the DOM node Suspense reveals it into -- verified
// live (a real user's machine, hardware-accelerated WebGL confirmed via
// chrome://gpu, extensions disabled, hard-refreshed, still broken) that
// this produced a map area with NO canvas, no zoom/attribution controls,
// and zero console errors: maplibre-gl's context-creation path failing
// silently against a container it received in this altered lifecycle,
// not a GPU/driver problem on that machine. Sidebar (also lazy, but
// with no native side effects) rendered correctly the whole time, which
// is what actually isolated the cause to lazy-loading + imperative
// WebGL specifically, not lazy-loading in general. LandingPage/
// ModeSelect stay eager too (the real first paint, cheap on their own).
import { Suspense, lazy, useState } from 'react'
import { AppStateProvider } from './state/AppStateContext'
import LandingPage from './components/LandingPage'
import ModeSelect from './components/ModeSelect'
import FirstVisitTour from './components/FirstVisitTour'
import MapView from './components/MapView'
import CitizenView from './components/CitizenView'

const Sidebar = lazy(() => import('./components/Sidebar'))
const ReportOverlay = lazy(() => import('./components/ReportOverlay'))
const DataGapNotice = lazy(() => import('./components/DataGapNotice'))
const MeteorFloodLegend = lazy(() => import('./components/MeteorFloodLegend'))

/** Shown while a lazy view's own chunk (+ maplibre-gl/geotiff.js, on first visit to either tool view) is still downloading -- a plain centered message rather than a blank white flash, styled with this app's own existing tokens so it doesn't look like an unstyled loading placeholder. */
function ViewLoadingFallback() {
  return (
    <div className="view-loading-fallback">
      <p>Loading…</p>
    </div>
  )
}

function App() {
  const [view, setView] = useState('landing')

  if (view === 'landing') {
    return (
      <AppStateProvider>
        <LandingPage onLaunch={() => setView('modes')} />
      </AppStateProvider>
    )
  }

  if (view === 'modes') {
    return (
      <AppStateProvider>
        <ModeSelect
          onCitizen={() => setView('citizen')}
          onResearcher={() => setView('tool')}
          onBack={() => setView('landing')}
        />
      </AppStateProvider>
    )
  }

  // Citizen Mode is deliberately outside AppStateProvider: it shares the
  // backend with the researcher tool, not the frontend state tree.
  // Eager import (see the top-of-file comment) -- no Suspense needed
  // here any more since CitizenView is no longer lazy.
  if (view === 'citizen') {
    return <CitizenView onBack={() => setView('modes')} />
  }

  return (
    <AppStateProvider>
      <Suspense fallback={<ViewLoadingFallback />}>
        <div className="app-layout">
          <Sidebar onBackToLanding={() => setView('modes')} />
          {/* .map-area wraps MapView plus everything that floats on top of
              it -- MapView's own root div is fully MapLibre-managed, so
              ReportOverlay/DataGapNotice are absolutely-positioned
              siblings here instead, one level up (see index.css). */}
          <div className="map-area">
            <MapView />
            <ReportOverlay />
            <DataGapNotice />
            <MeteorFloodLegend />
          </div>
        </div>
        {/* Inside the same Suspense boundary as Sidebar/MapView (not a
            sibling of it) so it only appears once the actual tool is on
            screen behind it, never popping in a beat earlier over the
            loading fallback. */}
        <FirstVisitTour />
      </Suspense>
    </AppStateProvider>
  )
}

export default App
