// The left-hand panel stack: one cohesive flow, AOI -> criteria ->
// weighting -> compute -> result, all reading/writing the same shared
// AppStateContext as the map. Each step's section is only shown once
// the previous one has something meaningful to act on, so the flow
// reads top-to-bottom rather than as disconnected views.
import { useAppState, useSelectedCriteriaIds } from '../state/AppStateContext'
import AOIPanel from './AOIPanel'
import CriteriaPanel from './CriteriaPanel'
import WeightingPanel from './WeightingPanel'
import ComputePanel from './ComputePanel'
import ResultPanel from './ResultPanel'

export default function Sidebar() {
  const { state, dispatch } = useAppState()
  const selectedIds = useSelectedCriteriaIds()

  return (
    <aside className="sidebar">
      <header className="sidebar__header">
        <div>
          <h1>Flood Risk Mapping</h1>
          <p>Kathmandu Valley</p>
        </div>
        <button
          type="button"
          className="theme-toggle"
          onClick={() => dispatch({ type: 'SET_THEME', theme: state.theme === 'dark' ? 'light' : 'dark' })}
          title={state.theme === 'dark' ? 'Switch to day mode' : 'Switch to night mode'}
          aria-label={state.theme === 'dark' ? 'Switch to day mode' : 'Switch to night mode'}
        >
          {state.theme === 'dark' ? '☀️' : '🌙'}
        </button>
      </header>

      <section className="sidebar__section">
        <h3>1. Area of interest</h3>
        <AOIPanel />
      </section>

      {state.aoi && (
        <section className="sidebar__section">
          <h3>2. Criteria</h3>
          <CriteriaPanel />
        </section>
      )}

      {state.aoi && selectedIds.length > 0 && (
        <section className="sidebar__section">
          <h3>3. Weighting</h3>
          <WeightingPanel />
        </section>
      )}

      {state.aoi && selectedIds.length > 0 && (
        <section className="sidebar__section">
          <h3>4. Compute</h3>
          <ComputePanel />
          <ResultPanel />
        </section>
      )}
    </aside>
  )
}
