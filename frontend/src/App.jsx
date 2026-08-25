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
import { useState } from 'react'
import { AppStateProvider } from './state/AppStateContext'
import LandingPage from './components/LandingPage'
import MapView from './components/MapView'
import Sidebar from './components/Sidebar'
import ModeSelect from './components/ModeSelect'
import CitizenView from './components/CitizenView'
import ReportOverlay from './components/ReportOverlay'
import DataGapNotice from './components/DataGapNotice'
import MeteorFloodLegend from './components/MeteorFloodLegend'

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
  if (view === 'citizen') {
    return <CitizenView onBack={() => setView('modes')} />
  }

  return (
    <AppStateProvider>
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
    </AppStateProvider>
  )
}

export default App
