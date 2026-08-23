// The left-hand panel stack: one cohesive flow, AOI -> criteria ->
// weighting -> compute -> result, all reading/writing the same shared
// AppStateContext as the map. Each step's section is only shown once
// the previous one has something meaningful to act on, so the flow
// reads top-to-bottom rather than as disconnected views.
import { useState } from 'react'
import { useAppState, useSelectedCriteriaIds } from '../state/AppStateContext'
import AboutModal from './AboutModal'
import AOIPanel from './AOIPanel'
import CriteriaPanel from './CriteriaPanel'
import Logo from './Logo'
import WeightingPanel from './WeightingPanel'
import ComputePanel from './ComputePanel'
import ResultPanel from './ResultPanel'
import ReportPanel from './ReportPanel'

export default function Sidebar({ onBackToLanding }) {
  const { state, dispatch } = useAppState()
  const selectedIds = useSelectedCriteriaIds()
  const [aboutOpen, setAboutOpen] = useState(false)

  return (
    <aside className="sidebar">
      <header className="sidebar__header">
        <button type="button" className="sidebar__brand" onClick={onBackToLanding} title="Back to overview">
          <Logo size={32} />
          <span>
            <span className="sidebar__brand-title">FloodHUB</span>
            <span className="sidebar__brand-sub">Kathmandu Valley</span>
          </span>
        </button>
        <div className="sidebar__header-actions">
          <button
            type="button"
            className="theme-toggle"
            onClick={() => setAboutOpen(true)}
            title="About this project"
            aria-label="About this project"
          >
            ℹ️
          </button>
          <button
            type="button"
            className="theme-toggle"
            onClick={() => dispatch({ type: 'SET_THEME', theme: state.theme === 'dark' ? 'light' : 'dark' })}
            title={state.theme === 'dark' ? 'Switch to day mode' : 'Switch to night mode'}
            aria-label={state.theme === 'dark' ? 'Switch to day mode' : 'Switch to night mode'}
          >
            {state.theme === 'dark' ? '☀️' : '🌙'}
          </button>
        </div>
      </header>

      {aboutOpen && <AboutModal onClose={() => setAboutOpen(false)} />}

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

      {state.overlay.status === 'loaded' && (
        <section className="sidebar__section">
          <h3>5. Vulnerability report</h3>
          <ReportPanel />
        </section>
      )}
    </aside>
  )
}
