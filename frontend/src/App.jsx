// One cohesive page: sidebar (AOI -> criteria -> weighting -> compute ->
// result) beside the map, both driven by the same AppStateContext. See
// src/state/AppStateContext.jsx for the shared state shape this whole
// tree reads/writes, and each component's own module docstring for its
// specific responsibility -- structured this way (context + small
// single-purpose components) specifically so a later phase
// (vulnerability classification, shelter markers) can extend this page
// rather than replace it.
import { AppStateProvider } from './state/AppStateContext'
import MapView from './components/MapView'
import Sidebar from './components/Sidebar'

function App() {
  return (
    <AppStateProvider>
      <div className="app-layout">
        <Sidebar />
        <MapView />
      </div>
    </AppStateProvider>
  )
}

export default App
