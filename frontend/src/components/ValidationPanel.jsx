// The sidebar's own "6. Validate" step: success-rate/AUC-checks the
// just-computed risk surface against a real, satellite-observed flood
// extent (POST /api/overlay/validate) -- never against another model's
// output (METEOR included; see backend/app/overlay/validate.py's own
// docstring for why that distinction was made deliberately, following
// this project's own earlier discussion on it -- METEOR agreement is
// its own separate step, MeteorComparisonPanel.jsx). Gated on
// state.overlay being loaded, same as ReportPanel -- this is a follow-up
// check on an EXISTING result, not a new computation of its own, and
// reuses that result's own criteriaUsed/weightsUsed snapshot rather than
// the live (possibly since-changed) criteria/weighting panels.
import { useEffect } from 'react'
import { listValidationEvents, validateRiskSurface } from '../api/client'
import { aucQuality } from '../lib/aucQuality'
import { formatFraction } from '../lib/formatFraction'
import { useAppState } from '../state/AppStateContext'
import FrequencyRatioChart from './FrequencyRatioChart'
import SuccessRateChart from './SuccessRateChart'

export default function ValidationPanel() {
  const { state, dispatch } = useAppState()
  const { criteriaUsed, weightsUsed } = state.overlay
  const eventsReady = state.validationEvents.status === 'loaded'

  // Fetched once, not tied to any particular compute result -- the list
  // of what's available to validate against never changes per-AOI.
  useEffect(() => {
    if (state.validationEvents.status !== 'idle') return
    dispatch({ type: 'VALIDATION_EVENTS_LOADING' })
    listValidationEvents()
      .then((events) => dispatch({ type: 'VALIDATION_EVENTS_LOADED', events }))
      .catch((error) => dispatch({ type: 'VALIDATION_EVENTS_ERROR', error }))
  }, [state.validationEvents.status, dispatch])

  if (state.overlay.status !== 'loaded' || !criteriaUsed || !weightsUsed) return null

  const { status, result, error } = state.validation

  async function handleValidate() {
    if (!state.selectedValidationEvent) return
    dispatch({ type: 'VALIDATION_LOADING' })
    try {
      const payload = {
        aoi: { bbox: state.aoi.bbox, polygon: state.aoi.polygon || null },
        criteria: criteriaUsed,
        final_weights: weightsUsed,
        complete: true,
        event: state.selectedValidationEvent,
      }
      const validationResult = await validateRiskSurface(payload)
      dispatch({ type: 'VALIDATION_LOADED', result: validationResult })
    } catch (err) {
      dispatch({ type: 'VALIDATION_ERROR', error: err })
    }
  }

  return (
    <div className="validation-panel">
      <p className="panel__hint">
        Checks this risk surface against a real, satellite-observed flood extent — not another model's estimate.
      </p>

      {state.validationEvents.status === 'loading' && <p className="panel__hint">Loading available events…</p>}
      {state.validationEvents.status === 'error' && (
        <p className="field-error">{state.validationEvents.error?.message || 'Could not load validation events.'}</p>
      )}

      {eventsReady && state.validationEvents.list.length === 0 && (
        <p className="panel__hint">No real flood events are registered to validate against yet.</p>
      )}

      {eventsReady && state.validationEvents.list.length > 0 && (
        <>
          <div className="validation-panel__event-picker">
            <label htmlFor="validation-event">Event</label>
            <select
              id="validation-event"
              value={state.selectedValidationEvent || ''}
              onChange={(e) => dispatch({ type: 'SET_VALIDATION_EVENT', event: e.target.value })}
            >
              {state.validationEvents.list.map((ev) => (
                <option key={ev.key} value={ev.key}>
                  {ev.label}
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            className="compute-button"
            disabled={status === 'loading' || !state.selectedValidationEvent}
            onClick={handleValidate}
          >
            {status === 'loading' ? 'Validating…' : result ? 'Re-validate' : 'Validate'}
          </button>
        </>
      )}

      {status === 'error' && <p className="field-error">{error?.message || 'Validation failed.'}</p>}

      {result && (
        <div className="validation-panel__result">
          <div className="validation-panel__auc">
            <span className="validation-panel__auc-value">{result.auc.toFixed(3)}</span>
            <span className="validation-panel__auc-label">
              AUC — <strong>{aucQuality(result.auc)}</strong>
            </span>
          </div>

          <p className="panel__hint">
            {formatFraction(result.observed_flooded_fraction)} of this AOI's valid pixels were actually flooded (
            {result.n_observed_flooded_pixels.toLocaleString()} of {result.n_valid_pixels.toLocaleString()} pixels
            compared) in {result.event_label}. For a point-inventory event this is a tiny number by design — one
            pixel per known occurrence location, not a filled extent.
          </p>

          <SuccessRateChart curve={result.curve} />

          <p className="panel__hint">
            <strong>Frequency ratio</strong>: of each hazard class's own pixels, what fraction really flooded — a
            well-behaved risk surface should show this increasing from Very Low to Very High.
          </p>
          <FrequencyRatioChart byClass={result.frequency_ratio} monotonic={result.monotonic} />

          <div className="attribution">
            <h5>Data attribution</h5>
            <ul>
              {result.attribution.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
