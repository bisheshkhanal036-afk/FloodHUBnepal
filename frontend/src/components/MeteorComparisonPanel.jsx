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
import { formatFraction } from '../lib/formatFraction'
import { useAppState } from '../state/AppStateContext'
import ErrorNotice from './ErrorNotice'
import FrequencyRatioChart from './FrequencyRatioChart'
import SuccessRateChart from './SuccessRateChart'

// The 3 flood types METEOR's own data actually distinguishes (FD/FU/P)
// -- a tiny label map, not shared/exported anywhere else, since this
// component only ever needs to *display* whichever one the backend's
// response says it actually compared against (config.METEOR_FLOOD_TYPE,
// fixed server-side, not caller-selectable).
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
    // Same double-click/double-Enter guard ReportPanel's own
    // handleGenerateReport documents.
    if (status === 'loading') return
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

      {status === 'error' && <ErrorNotice error={error} fallback="Comparison failed." onRetry={handleCompare} />}

      {result && (
        <div className="validation-panel__result">
          <div className="validation-panel__auc">
            <span className="validation-panel__auc-value">{result.auc.toFixed(3)}</span>
            <span className="validation-panel__auc-label">
              AUC — <strong>{aucQuality(result.auc)}</strong> agreement
            </span>
          </div>

          <p className="panel__hint">
            METEOR models {formatFraction(result.meteor_flooded_fraction)} of this AOI's valid pixels as flooded (
            {result.n_meteor_flooded_pixels.toLocaleString()} of {result.n_valid_pixels.toLocaleString()} pixels
            compared) under {formatFloodType(result.meteor_flood_type)}, {formatReturnPeriod(result.meteor_return_period)}.
          </p>

          <SuccessRateChart curve={result.curve} capturedLabel="METEOR-modeled flooding" />

          <p className="panel__hint">
            <strong>Frequency ratio</strong>: of each hazard class's own pixels, what fraction METEOR also models as
            flooded — a well-behaved risk surface should show this increasing from Very Low to Very High.
          </p>
          <FrequencyRatioChart byClass={result.frequency_ratio} monotonic={result.monotonic} />

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
