// "Compute risk map" button: builds the POST /api/overlay/compute/stream
// request from the current AOI + selected criteria (with their default
// reclassification_rules, src/config/criteria.js) + final_weights
// (src/state/AppStateContext.jsx's useFinalWeights), and shows the
// loading/error/disabled-reason states the brief calls for.
//
// Uses the STREAMING endpoint (computeOverlayStream), not the plain
// computeOverlay -- real per-step progress from the backend (see
// api/client.js's own docstring for why this isn't a fabricated/
// animated progress bar), rendered live below the button as each SSE
// event arrives.
import { useEffect, useRef } from 'react'
import { computeOverlayStream } from '../api/client'
import { CRITERIA_BY_ID } from '../config/criteria'
import { rulesForClassification } from '../lib/classification'
import { useAppState, useFinalWeights, useSelectedCriteriaIds } from '../state/AppStateContext'

// dist_to_road/dist_to_river both read from a local OSM .pbf extract
// when one is present (app/data/osm.py) -- parsing a real, full Nepal
// extract for the first time is genuinely slow (~150-200s+ measured
// live against a real 412MB file, on a cache miss), not just "a few
// seconds" like the other 5 sources. Shown only when relevant so the
// loading message stays accurate without alarming every request.
const OSM_BACKED_SOURCES = new Set(['dist_to_road', 'dist_to_river'])

export default function ComputePanel() {
  const { state, dispatch } = useAppState()
  const selectedIds = useSelectedCriteriaIds()
  const progressLogRef = useRef(null)

  // Auto-scroll to the latest step, same as any live log/console tail --
  // .compute-progress is a fixed-height scrollable list (max-height in
  // index.css), so without this it stays scrolled to the top and only
  // the first few of a longer log are ever visible.
  useEffect(() => {
    const el = progressLogRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [state.overlay.progressLog])

  const { finalWeights, complete, reason } = useFinalWeights()
  const usesOsmSource = selectedIds.some((id) => OSM_BACKED_SOURCES.has(id))

  const missingAoi = !state.aoi
  const unorderedBreaksCriterion = selectedIds.find((id) => {
    const entry = state.classification[id]
    if (!entry || CRITERIA_BY_ID[id].type === 'categorical') return false
    return !entry.breaks.every((b, i) => i === 0 || b > entry.breaks[i - 1])
  })
  const disabled = missingAoi || !complete || !!unorderedBreaksCriterion || state.overlay.status === 'loading'

  let disabledReason = null
  if (missingAoi) disabledReason = 'Select an AOI first.'
  else if (unorderedBreaksCriterion) {
    disabledReason = `${CRITERIA_BY_ID[unorderedBreaksCriterion].label}'s breaks must be in increasing order.`
  } else if (!complete) disabledReason = reason

  async function handleCompute() {
    if (disabled) return
    dispatch({ type: 'OVERLAY_LOADING' })
    try {
      const criteria = selectedIds.map((id) => ({
        id,
        source: id,
        reclassification_rules: rulesForClassification(CRITERIA_BY_ID[id], state.classification[id]),
      }))
      const payload = {
        aoi: { bbox: state.aoi.bbox, polygon: state.aoi.polygon || null },
        criteria,
        final_weights: finalWeights,
        complete: true,
      }
      const result = await computeOverlayStream(payload, (message) =>
        dispatch({ type: 'OVERLAY_PROGRESS', message })
      )
      dispatch({ type: 'OVERLAY_LOADED', result, criteriaUsed: criteria, weightsUsed: finalWeights })
    } catch (error) {
      dispatch({ type: 'OVERLAY_ERROR', error })
    }
  }

  return (
    <div className="compute-panel">
      <button type="button" className="compute-button" disabled={disabled} onClick={handleCompute}>
        {state.overlay.status === 'loading' ? 'Computing…' : 'Compute risk map'}
      </button>
      {disabled && disabledReason && !missingAoi && state.overlay.status !== 'loading' && (
        <p className="panel__hint">{disabledReason}</p>
      )}
      {missingAoi && <p className="panel__hint">{disabledReason}</p>}
      {state.overlay.status === 'loading' && usesOsmSource && (
        <p className="panel__hint">
          A road/river-distance criterion is selected — the first parse of a real local OSM extract can take several
          minutes on a cache miss.
        </p>
      )}
      {state.overlay.status === 'error' && (
        <p className="field-error">{state.overlay.error?.message || 'Computation failed.'}</p>
      )}
      {state.overlay.progressLog.length > 0 && (
        <ul className="compute-progress" ref={progressLogRef}>
          {state.overlay.progressLog.map((message, i) => {
            const isLast = i === state.overlay.progressLog.length - 1
            const stillRunning = isLast && state.overlay.status === 'loading'
            return (
              <li key={i} className={stillRunning ? 'compute-progress__step compute-progress__step--active' : 'compute-progress__step'}>
                {stillRunning ? '⏳' : '✓'} {message}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
