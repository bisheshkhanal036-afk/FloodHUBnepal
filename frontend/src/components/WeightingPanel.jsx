// Weight-mode toggle -- "Use equal weights" (default, immediately
// computable client-side, see useFinalWeights), "Customize weights with
// AHP" (full pairwise comparison UI), or "Type weights" (direct numeric
// entry, normalized to sum to 1) -- plus whichever mode's content.
// Switching back to equal weights after entering AHP or manual mode
// discards whatever work was done there, so that direction is confirmed
// first; entering AHP/manual mode is always non-destructive (equal mode
// has nothing to lose, and AHP/manual state persists across toggling
// between the two of them).
import { CRITERIA_BY_ID } from '../config/criteria'
import { isDefaultMatrix } from '../lib/ahpMatrix'
import { useAppState, useFinalWeights, useSelectedCriteriaIds } from '../state/AppStateContext'
import AHPPanel from './AHPPanel'
import ManualWeightsPanel from './ManualWeightsPanel'

const MODES = [
  { id: 'equal', label: 'Use equal weights' },
  { id: 'ahp', label: 'Customize weights with AHP' },
  { id: 'manual', label: 'Type weights' },
]

function hasAhpWork(ahpMatrices) {
  return !isDefaultMatrix(ahpMatrices.cluster.matrix) || Object.values(ahpMatrices.withinCluster).some((m) => !isDefaultMatrix(m.matrix))
}

function hasManualWork(manualWeights) {
  const values = Object.values(manualWeights)
  if (values.length < 2) return false
  return values.some((v) => v !== values[0])
}

export default function WeightingPanel() {
  const { state, dispatch } = useAppState()
  const selectedIds = useSelectedCriteriaIds()
  const { finalWeights } = useFinalWeights()

  if (selectedIds.length === 0) {
    return <p className="panel__hint">Check at least one criterion above to set weights.</p>
  }

  function switchTo(mode) {
    if (mode === state.weightMode) return
    if (mode === 'equal') {
      const wouldDiscard =
        (state.weightMode === 'ahp' && hasAhpWork(state.ahpMatrices)) ||
        (state.weightMode === 'manual' && hasManualWork(state.manualWeights))
      if (wouldDiscard) {
        const label = state.weightMode === 'ahp' ? 'AHP pairwise comparisons' : 'typed weights'
        if (!window.confirm(`Switching to equal weights will discard your ${label}. Continue?`)) return
      }
    }
    dispatch({ type: 'SET_WEIGHT_MODE', mode })
  }

  return (
    <div className="weighting-panel">
      <div className="mode-toggle mode-toggle--triple">
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            className={`mode-toggle__button ${state.weightMode === m.id ? 'mode-toggle__button--active' : ''}`}
            onClick={() => switchTo(m.id)}
          >
            {m.label}
          </button>
        ))}
      </div>

      {state.weightMode === 'equal' && finalWeights && (
        <ul className="weights-list">
          {selectedIds.map((id) => (
            <li key={id}>
              <span>{CRITERIA_BY_ID[id].label}</span>
              <span className="weights-list__value">{(finalWeights[id] * 100).toFixed(1)}%</span>
            </li>
          ))}
        </ul>
      )}

      {state.weightMode === 'ahp' && <AHPPanel />}
      {state.weightMode === 'manual' && <ManualWeightsPanel />}
    </div>
  )
}
