// The sidebar's own "7. Compare to METEOR" step: checks agreement
// between the just-computed risk surface and METEOR's own modeled flood
// hazard (POST /api/overlay/compare-meteor) -- a DELIBERATELY separate
// step/component from ValidationPanel.jsx, never the same "Validate"
// language or the same event picker, because this measures agreement
// between two independently-produced models, not real-world accuracy
// (see backend/app/overlay/meteor_comparison.py's own module docstring
// for the full reasoning, following this project's own earlier
// discussion establishing that distinction). Gated on state.overlay
// being loaded, same as ValidationPanel/ReportPanel.
import { useState } from 'react'
import { compareToMeteor } from '../api/client'
import { aucQuality } from '../lib/aucQuality'
import { useAppState } from '../state/AppStateContext'
import PrecisionRecallChart from './PrecisionRecallChart'
import SuccessRateChart from './SuccessRateChart'

// Same three flood types MapView.jsx's own METEOR overlay control
// offers (METEOR_FLOOD_TYPES there) -- duplicated as a tiny label map
// rather than exported/shared, since it's three fixed strings, not
// logic, and this component only ever needs to *display* whichever one
// the backend's response says it actually compared against.
const METEOR_FLOOD_TYPE_LABELS = { FD: 'Fluvial (Defended)', FU: 'Fluvial (Undefended)', P: 'Pluvial' }

function formatFloodType(type) {
  return METEOR_FLOOD_TYPE_LABELS[type?.toUpperCase()] || type
}

function formatReturnPeriod(period) {
  const match = /^(\d+)in(\d+)$/.exec(period || '')
  return match ? `1-in-${match[2]}y` : period
}

export default function MeteorComparisonPanel() {
  const { state, dispatch } = useAppState()
  const { criteriaUsed, weightsUsed } = state.overlay
  const [expanded, setExpanded] = useState(false)

  if (state.overlay.status !== 'loaded' || !criteriaUsed || !weightsUsed) return null

  const { status, result, error } = state.meteorComparison

  async function handleCompare() {
    dispatch({ type: 'METEOR_COMPARISON_LOADING' })
    try {
      const payload = {
        aoi: { bbox: state.aoi.bbox, polygon: state.aoi.polygon || null },
        criteria: criteriaUsed,
        final_weights: weightsUsed,
        complete: true,
      }
      const comparisonResult = await compareToMeteor(payload)
      dispatch({ type: 'METEOR_COMPARISON_LOADED', result: comparisonResult })
    } catch (err) {
      dispatch({ type: 'METEOR_COMPARISON_ERROR', error: err })
    }
  }

  return (
    <div className="validation-panel">
      <p className="panel__hint panel__hint--warning">
        This checks <strong>agreement with another model</strong> (METEOR/Fathom's own flood hazard map) — it is not
        a check against real-world accuracy. For that, see the <strong>Validate</strong> step above, which compares
        against a real, satellite-observed flood extent instead.
      </p>

      <button type="button" className="compute-button" disabled={status === 'loading'} onClick={handleCompare}>
        {status === 'loading' ? 'Comparing…' : result ? 'Re-compare' : 'Compare to METEOR'}
      </button>

      {status === 'error' && <p className="field-error">{error?.message || 'Comparison failed.'}</p>}

      {result && (
        <div className="validation-panel__result">
          <div className="validation-panel__auc">
            <span className="validation-panel__auc-value">{result.auc.toFixed(3)}</span>
            <span className="validation-panel__auc-label">
              AUC — <strong>{aucQuality(result.auc)}</strong> agreement
            </span>
          </div>

          <p className="panel__hint">
            METEOR models {(result.meteor_flooded_fraction * 100).toFixed(1)}% of this AOI as flooded (
            {result.n_meteor_flooded_pixels.toLocaleString()} of {result.n_valid_pixels.toLocaleString()} pixels
            compared) under {formatFloodType(result.meteor_flood_type)}, {formatReturnPeriod(result.meteor_return_period)}.
          </p>

          <SuccessRateChart curve={result.curve} capturedLabel="METEOR-modeled flooding" />

          <div className="validation-panel__metrics">
            <div className="validation-panel__metric">
              <span className="validation-panel__metric-value">{result.precision.toFixed(2)}</span>
              <span className="validation-panel__metric-label">Precision</span>
            </div>
            <div className="validation-panel__metric">
              <span className="validation-panel__metric-value">{result.recall.toFixed(2)}</span>
              <span className="validation-panel__metric-label">Recall</span>
            </div>
            <div className="validation-panel__metric">
              <span className="validation-panel__metric-value">{result.f1.toFixed(2)}</span>
              <span className="validation-panel__metric-label">F1</span>
            </div>
            <div className="validation-panel__metric">
              <span className="validation-panel__metric-value">{result.iou.toFixed(2)}</span>
              <span className="validation-panel__metric-label">IoU</span>
            </div>
          </div>
          <p className="panel__hint">
            Precision/recall/F1/IoU compare this AOI's <strong>High</strong> and <strong>Very High</strong> hazard
            pixels directly against METEOR's own modeled flood extent (a single fixed threshold, unlike the two
            curves below, which sweep every possible cutoff).
          </p>

          <div className="validation-panel__pr-auc">
            <span className="validation-panel__pr-auc-value">{result.pr_auc.toFixed(3)}</span>
            <span className="validation-panel__pr-auc-label">
              PR-AUC — compare against {(result.meteor_flooded_fraction * 100).toFixed(1)}% (random baseline), not 0.5
            </span>
          </div>
          <PrecisionRecallChart curve={result.precision_recall_curve} observedFloodedFraction={result.meteor_flooded_fraction} />

          <button type="button" className="link-button" onClick={() => setExpanded((v) => !v)}>
            {expanded ? 'Hide' : 'Show'} data attribution
          </button>
          {expanded && (
            <div className="attribution">
              <h5>Data attribution</h5>
              <ul>
                {result.attribution.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
