// One cohesive page: sidebar (AOI -> criteria -> weighting -> compute ->
// result) beside the map, both driven by the same AppStateContext. See
// src/state/AppStateContext.jsx for the shared state shape this whole
// tree reads/writes, and each component's own module docstring for its
// specific responsibility -- structured this way (context + small
// single-purpose components) specifically so a later phase
// (vulnerability classification, shelter markers) can extend this page
// rather than replace it.
//
// `view` ('landing' | 'tool') is local, presentation-only navigation
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

function App() {
  const [view, setView] = useState('landing')

  return (
    <AppStateProvider>
      {view === 'landing' ? (
        <LandingPage onLaunch={() => setView('tool')} />
      ) : (
        <div className="app-layout">
          <Sidebar onBackToLanding={() => setView('landing')} />
          <MapView />
        </div>
      )}
    </AppStateProvider>
  )
}

export default App
