// The left-hand panel stack: one cohesive flow, AOI -> criteria ->
// weighting -> compute -> result, all reading/writing the same shared
// AppStateContext as the map. Rendered as a connected step-rail (see
// StepSection.jsx) rather than plain stacked cards -- each step is only
// reachable once the previous one has something meaningful to act on
// (unchanged from before: a not-yet-reachable step's own panel component
// is never mounted, only its header shows, dimmed). Every reachable step
// is open by default, same as the original always-expanded layout; a
// step can be collapsed by clicking its header, purely as an opt-in
// convenience for a step you're done with (see isOpen's own comment
// below for why this isn't automatic). Collapsing is local UI state only
// (`overrides` below) -- it never touches AppStateContext, so it can't
// affect which data is actually submitted anywhere.
import { useMemo, useState } from 'react'
import { useAppState, useFinalWeights, useSelectedCriteriaIds } from '../state/AppStateContext'
import AboutModal from './AboutModal'
import AOIPanel from './AOIPanel'
import CriteriaPanel from './CriteriaPanel'
import Logo from './Logo'
import StepSection from './StepSection'
import WeightingPanel from './WeightingPanel'
import ComputePanel from './ComputePanel'
import ResultPanel from './ResultPanel'
import ReportPanel from './ReportPanel'

export default function Sidebar({ onBackToLanding }) {
  const { state, dispatch } = useAppState()
  const selectedIds = useSelectedCriteriaIds()
  const { complete: weightsComplete } = useFinalWeights()
  const [aboutOpen, setAboutOpen] = useState(false)
  const [overrides, setOverrides] = useState({})

  const steps = useMemo(() => {
    const hasAoi = !!state.aoi
    const hasCriteria = selectedIds.length > 0
    const weightingReady = hasCriteria && weightsComplete
    const overlayLoaded = state.overlay.status === 'loaded'
    const reportLoaded = state.report.status === 'loaded'

    return [
      { id: 1, title: 'Area of interest', reachable: true, complete: hasAoi, content: <AOIPanel /> },
      { id: 2, title: 'Criteria', reachable: hasAoi, complete: hasCriteria, content: <CriteriaPanel /> },
      { id: 3, title: 'Weighting', reachable: hasAoi && hasCriteria, complete: weightingReady, content: <WeightingPanel /> },
      {
        id: 4,
        title: 'Compute',
        reachable: hasAoi && hasCriteria,
        complete: overlayLoaded,
        content: (
          <>
            <ComputePanel />
            <ResultPanel />
          </>
        ),
      },
      { id: 5, title: 'Vulnerability report', reachable: overlayLoaded, complete: reportLoaded, content: <ReportPanel /> },
    ]
  }, [state.aoi, selectedIds.length, weightsComplete, state.overlay.status, state.report.status])

  // Every reachable step is open by default -- deliberately NOT an
  // accordion that auto-collapses a step the instant it's "complete"
  // (e.g. the Criteria step becomes "complete" the moment a single
  // checkbox is checked, since that's the same threshold that unlocks
  // Weighting -- auto-collapsing right then would yank the checkbox list
  // away from someone who's only picked their first of several
  // criteria). Collapsing is purely an opt-in convenience: any step can
  // still be manually closed (and reopened) via `overrides`, which
  // always wins over this default.
  function isOpen(step) {
    if (step.id in overrides) return overrides[step.id]
    return true
  }

  function toggle(step) {
    setOverrides((prev) => ({ ...prev, [step.id]: !isOpen(step) }))
  }

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

      <div className="step-rail">
        {steps.map((step, i) => {
          const status = !step.reachable ? 'locked' : step.complete ? 'complete' : 'active'
          return (
            <StepSection
              key={step.id}
              number={step.id}
              title={step.title}
              status={status}
              isLast={i === steps.length - 1}
              isOpen={step.reachable && isOpen(step)}
              onToggle={() => toggle(step)}
            >
              {step.content}
            </StepSection>
          )
        })}
      </div>
    </aside>
  )
}
