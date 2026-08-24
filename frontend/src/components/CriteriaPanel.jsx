// Checkbox list of the available criteria, grouped by their AHP cluster
// (see src/config/criteria.js for the id -> cluster assignment). Each row
// carries a per-feature info (ⓘ) button that opens LiteratureModal — the
// well-cited write-up of what the feature is and how its reclassification
// ranges are set (src/config/literature.js). Each checked criterion also
// gets an expandable "Customize breaks" section (ClassificationEditor).
import { useState } from 'react'
import { CANONICAL_CLUSTERS, criteriaByCluster, STREAM_THRESHOLD_SOURCE_IDS } from '../config/criteria'
import { LITERATURE } from '../config/literature'
import { useAppState } from '../state/AppStateContext'
import ClassificationEditor from './ClassificationEditor'
import LiteratureModal from './LiteratureModal'

// The grid's own resolution is fixed at 10m everywhere (SPEC.md §2.2) --
// safe to hardcode here purely for this display-only "≈ X km²" helper
// text, not used for anything the backend actually computes with.
const GRID_RESOLUTION_M = 10
const PIXEL_AREA_KM2 = (GRID_RESOLUTION_M * GRID_RESOLUTION_M) / 1_000_000

function StreamThresholdControl() {
  const { state, dispatch } = useAppState()
  const areaKm2 = state.streamThresholdCells * PIXEL_AREA_KM2

  return (
    <div className="criteria-panel__stream-threshold">
      <h4>Stream network threshold</h4>
      <p className="panel__hint">
        Shared by Drainage Density and HAND — both are measured against the same synthetic stream
        network. A pixel counts as "stream" once at least this many upstream pixels drain through it.
      </p>
      <label className="criteria-panel__stream-threshold-input">
        <input
          type="number"
          min="1"
          step="1"
          value={state.streamThresholdCells}
          onChange={(e) => {
            const value = Number(e.target.value)
            if (Number.isFinite(value) && value >= 1) {
              dispatch({ type: 'SET_STREAM_THRESHOLD_CELLS', cells: Math.round(value) })
            }
          }}
        />
        <span>cells</span>
      </label>
      <p className="panel__hint criteria-panel__stream-threshold-area">
        ≈ {areaKm2.toFixed(2)} km² of contributing area, at {GRID_RESOLUTION_M}m resolution.
      </p>
    </div>
  )
}

export default function CriteriaPanel() {
  const { state, dispatch } = useAppState()
  const byCluster = criteriaByCluster()
  const showStreamThreshold = STREAM_THRESHOLD_SOURCE_IDS.some((id) => state.criteriaEnabled[id])
  // Which feature's literature is open in the modal (null = closed).
  const [litFocusId, setLitFocusId] = useState(null)

  return (
    <div className="criteria-panel">
      <button
        type="button"
        className="link-button criteria-panel__select-all"
        onClick={() => dispatch({ type: 'SELECT_ALL_CRITERIA' })}
      >
        Select all
      </button>
      {CANONICAL_CLUSTERS.map((cluster) => (
        <div className="criteria-panel__cluster" key={cluster}>
          <h4>{cluster}</h4>
          {byCluster[cluster].map((criterion) => (
            <div key={criterion.id}>
              <div className="criteria-panel__row">
                <label className="criteria-panel__item" title={criterion.description}>
                  <input
                    type="checkbox"
                    checked={state.criteriaEnabled[criterion.id]}
                    onChange={() => dispatch({ type: 'TOGGLE_CRITERION', id: criterion.id })}
                  />
                  <span>
                    {criterion.label}
                    {criterion.unit ? <span className="criteria-panel__unit"> ({criterion.unit})</span> : null}
                  </span>
                </label>
                {LITERATURE[criterion.id] && (
                  <button
                    type="button"
                    className="criteria-panel__info"
                    onClick={() => setLitFocusId(criterion.id)}
                    title={`What is ${criterion.label}? Literature & how its ranges are set`}
                    aria-label={`Literature for ${criterion.label}`}
                  >
                    ⓘ
                  </button>
                )}
              </div>
              {state.criteriaEnabled[criterion.id] && (
                <details className="criteria-panel__classification">
                  <summary>Customize breaks</summary>
                  <ClassificationEditor criterion={criterion} />
                </details>
              )}
            </div>
          ))}
        </div>
      ))}
      {showStreamThreshold && <StreamThresholdControl />}

      {litFocusId && <LiteratureModal focusId={litFocusId} onClose={() => setLitFocusId(null)} />}
    </div>
  )
}
