// Per-criterion reclassification editor: pick a classification method
// (Manual / Equal Interval / Quantile / Jenks Natural Breaks) for a
// continuous criterion, or edit the risk class per legend code for a
// categorical one (worldcover_land_cover) -- there's no "breaks" concept
// for discrete category codes, so that case skips the method selector
// entirely. Equal-interval/quantile/Jenks are computed server-side
// (POST /api/overlay/criteria/breaks), since they need the criterion's
// actual raw value distribution over the current AOI, which only the
// backend can compute. A live preview (reusing ReclassificationTable)
// always reflects whatever's currently active, whether hand-typed or
// fetched.
import { useEffect } from 'react'
import { computeCriterionBreaks } from '../api/client'
import { WORLDCOVER_LABELS } from '../config/criteria'
import { breaksToRules, selectClassificationMethod } from '../lib/classification'
import { useAppState } from '../state/AppStateContext'
import ReclassificationTable from './ReclassificationTable'

const METHODS = [
  { id: 'manual', label: 'Manual' },
  { id: 'equal_interval', label: 'Equal Interval' },
  { id: 'quantile', label: 'Quantile' },
  { id: 'jenks', label: 'Jenks Natural Breaks' },
]

export default function ClassificationEditor({ criterion }) {
  const { state, dispatch } = useAppState()
  const entry = state.classification[criterion.id]
  if (!entry) return null

  if (criterion.type === 'categorical') {
    return <CategoricalEditor criterion={criterion} entry={entry} dispatch={dispatch} />
  }
  return (
    <ContinuousEditor
      criterion={criterion}
      entry={entry}
      aoi={state.aoi}
      streamThresholdCells={state.streamThresholdCells}
      dispatch={dispatch}
    />
  )
}

function ContinuousEditor({ criterion, entry, aoi, streamThresholdCells, dispatch }) {
  const { method, breaks, fetch } = entry

  // Fetch candidate breaks once per (criterion, AOI) whenever a
  // non-manual method is selected and hasn't been fetched yet -- not on
  // every method switch, so flipping back and forth between e.g.
  // Quantile and Jenks after the first fetch is instant (the response
  // already carries all 3 methods' breaks at once). For drainage_density/
  // hand, a stream-threshold change resets fetch.status back to 'idle'
  // (AppStateContext's SET_STREAM_THRESHOLD_CELLS reducer case) so this
  // effect re-fires the same way an AOI change already does -- no
  // separate streamThresholdCells dependency needed here, just always
  // send its current value whenever a fetch does happen.
  useEffect(() => {
    if (method === 'manual' || fetch.status !== 'idle' || !aoi) return
    dispatch({ type: 'CLASSIFICATION_BREAKS_LOADING', id: criterion.id })
    computeCriterionBreaks({
      aoi: { bbox: aoi.bbox, polygon: aoi.polygon || null },
      source: criterion.id,
      stream_threshold_cells: streamThresholdCells,
    })
      .then((data) => {
        dispatch({ type: 'CLASSIFICATION_BREAKS_LOADED', id: criterion.id, data })
        dispatch({ type: 'SET_CLASSIFICATION_BREAKS', id: criterion.id, breaks: data[method] })
      })
      .catch((error) => dispatch({ type: 'CLASSIFICATION_BREAKS_ERROR', id: criterion.id, error }))
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-fetch only on method/aoi/fetch.status change, not on every breaks edit
  }, [method, aoi, criterion.id, fetch.status])

  function selectMethod(newMethod) {
    if (newMethod === 'manual') {
      dispatch({ type: 'SET_CLASSIFICATION_METHOD', id: criterion.id, method: newMethod })
      return
    }
    selectClassificationMethod(dispatch, criterion.id, newMethod, entry)
  }

  function editBreak(index, rawValue) {
    const value = Number(rawValue)
    const next = [...breaks]
    next[index] = Number.isFinite(value) ? value : next[index]
    dispatch({ type: 'SET_CLASSIFICATION_BREAKS', id: criterion.id, breaks: next })
  }

  const breaksAscending = breaks.every((b, i) => i === 0 || b > breaks[i - 1])
  const previewRules = breaksToRules(breaks, criterion.riskDirection)

  return (
    <div className="classification-editor">
      <div className="classification-editor__methods">
        {METHODS.map((m) => (
          <button
            key={m.id}
            type="button"
            className={`classification-editor__method ${method === m.id ? 'classification-editor__method--active' : ''}`}
            onClick={() => selectMethod(m.id)}
          >
            {m.label}
          </button>
        ))}
      </div>

      {fetch.status === 'loading' && method !== 'manual' && (
        <p className="panel__hint">Computing {METHODS.find((m) => m.id === method).label.toLowerCase()} breaks…</p>
      )}
      {fetch.status === 'error' && method !== 'manual' && (
        <p className="field-error">{fetch.error?.message || 'Could not compute breaks.'}</p>
      )}
      {fetch.status === 'loaded' && (
        <p className="panel__hint">
          Data range: {fetch.min.toFixed(2)} to {fetch.max.toFixed(2)} ({fetch.valid_pixel_count.toLocaleString()} pixels)
        </p>
      )}

      <div className="classification-editor__breaks">
        {breaks.map((b, i) => (
          <label key={i} className="classification-editor__break">
            Break {i + 1}
            <input
              type="number"
              step="any"
              value={b}
              onChange={(e) => editBreak(i, e.target.value)}
              className="classification-editor__break-input"
            />
          </label>
        ))}
      </div>
      {!breaksAscending && <p className="field-error">Breaks must be in increasing order.</p>}

      <ReclassificationTable criterion={criterion} rules={previewRules} />
    </div>
  )
}

function CategoricalEditor({ criterion, entry, dispatch }) {
  const { riskClassByCode } = entry
  const codes = Object.keys(riskClassByCode)
    .map(Number)
    .sort((a, b) => a - b)

  return (
    <div className="classification-editor">
      <p className="panel__hint">Manual only — set the risk class for each land cover type directly.</p>
      <table className="reclass-table">
        <tbody>
          {codes.map((code) => (
            <tr key={code}>
              <td className="reclass-table__range">
                {WORLDCOVER_LABELS[code] || code} ({code})
              </td>
              <td className="reclass-table__arrow">→</td>
              <td>
                <select
                  value={riskClassByCode[code]}
                  onChange={(e) =>
                    dispatch({
                      type: 'SET_CLASSIFICATION_CODE_CLASS',
                      id: criterion.id,
                      code,
                      riskClass: Number(e.target.value),
                    })
                  }
                >
                  {[1, 2, 3, 4, 5].map((c) => (
                    <option key={c} value={c}>
                      class {c}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
