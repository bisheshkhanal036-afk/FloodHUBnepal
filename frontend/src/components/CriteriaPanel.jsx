// Checkbox list of the available criteria, grouped by their AHP cluster
// (see src/config/criteria.js for the id -> cluster assignment). Each row
// carries a per-feature info (ⓘ) button that opens LiteratureModal — the
// well-cited write-up of what the feature is and how its reclassification
// ranges are set (src/config/literature.js). Each checked criterion also
// gets an expandable "Customize breaks" section (ClassificationEditor).
import { useState } from 'react'
import { CANONICAL_CLUSTERS, CRITERIA_BY_ID, criteriaByCluster, STREAM_THRESHOLD_SOURCE_IDS } from '../config/criteria'
import { LITERATURE } from '../config/literature'
import { selectClassificationMethod } from '../lib/classification'
import { useAppState } from '../state/AppStateContext'
import ClassificationEditor from './ClassificationEditor'
import LiteratureModal from './LiteratureModal'

// Same 3 non-manual methods ClassificationEditor.jsx's own per-criterion
// picker offers -- 'jenks' (Fisher-Jenks "Natural Breaks") is this bulk
// action's own default, not 'quantile'/'equal_interval': it's the one
// method actually named for and designed to find natural clusters in a
// variable's own real distribution, the closest match to "remake the
// classes based on the features of that area" of the three.
const AUTO_METHODS = [
  { id: 'jenks', label: 'Natural Breaks (Jenks)' },
  { id: 'quantile', label: 'Quantile' },
  { id: 'equal_interval', label: 'Equal Interval' },
]

/**
 * "Auto-classify all" -- a bulk shortcut over the exact same per-
 * criterion machinery ClassificationEditor.jsx's own method buttons
 * already use (selectClassificationMethod), applied to every checked
 * CONTINUOUS criterion at once (categorical criteria -- currently only
 * worldcover_land_cover -- have no "breaks" concept at all, manual per-
 * code assignment only, so they're silently skipped here rather than
 * erroring). Visible once an AOI is set (drawn, or selected via basin/
 * district -- all three set the same state.aoi shape, so this isn't
 * restricted to any one selection mode) and at least one criterion is
 * checked, matching the request this was built for: an option to remake
 * the classes automatically, based on the actual data in that area,
 * once a basin and criteria are both selected.
 */
function AutoClassifyAll({ continuousCheckedIds, categoricalCheckedCount, aoiReady }) {
  const { state, dispatch } = useAppState()
  const [method, setMethod] = useState('jenks')

  if (!aoiReady || continuousCheckedIds.length === 0) return null

  function handleAutoClassify() {
    for (const id of continuousCheckedIds) {
      selectClassificationMethod(dispatch, id, method, state.classification[id])
    }
  }

  const entries = continuousCheckedIds.map((id) => state.classification[id]).filter(Boolean)
  const loadingCount = entries.filter((e) => e.fetch.status === 'loading').length
  const errorCount = entries.filter((e) => e.fetch.status === 'error').length
  // Requires fetch.status === 'loaded', not just method === method --
  // right after clicking, selectClassificationMethod has already set
  // .method for every criterion on this same render, but the ones that
  // needed a fetch are still 'idle' for one tick until their own effect
  // dispatches CLASSIFICATION_BREAKS_LOADING. Counting on .method alone
  // would claim "All N applied" before the real breaks values landed.
  const appliedCount = entries.filter((e) => e.method === method && e.fetch.status === 'loaded').length

  return (
    <div className="auto-classify">
      <div className="auto-classify__row">
        <select
          className="auto-classify__method"
          value={method}
          onChange={(e) => setMethod(e.target.value)}
          title="Which automatic classification method to apply to every checked criterion"
        >
          {AUTO_METHODS.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
        <button type="button" className="link-button" onClick={handleAutoClassify}>
          Auto-classify all ({continuousCheckedIds.length})
        </button>
      </div>
      <p className="panel__hint">
        Recomputes each checked criterion's risk classes from its own real value distribution within
        the current area, instead of the static defaults.
        {categoricalCheckedCount > 0 &&
          ` (${categoricalCheckedCount} checked ${categoricalCheckedCount > 1 ? 'criteria are' : 'criterion is'} categorical and always classified manually, unaffected.)`}
      </p>
      {loadingCount > 0 && <p className="panel__hint">Computing {method.replace('_', ' ')} breaks for {loadingCount} criteria…</p>}
      {errorCount > 0 && <p className="field-error">{errorCount} criteria failed to auto-classify — see each one's own "Customize breaks" section.</p>}
      {loadingCount === 0 && errorCount === 0 && appliedCount === continuousCheckedIds.length && (
        <p className="panel__hint">All {appliedCount} applied.</p>
      )}
    </div>
  )
}

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

  const checkedIds = Object.keys(state.criteriaEnabled).filter((id) => state.criteriaEnabled[id])
  const continuousCheckedIds = checkedIds.filter((id) => CRITERIA_BY_ID[id].type !== 'categorical')
  const categoricalCheckedCount = checkedIds.length - continuousCheckedIds.length

  return (
    <div className="criteria-panel">
      <button
        type="button"
        className="link-button criteria-panel__select-all"
        onClick={() => dispatch({ type: 'SELECT_ALL_CRITERIA' })}
      >
        Select all
      </button>
      <AutoClassifyAll
        continuousCheckedIds={continuousCheckedIds}
        categoricalCheckedCount={categoricalCheckedCount}
        aoiReady={!!state.aoi}
      />
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
