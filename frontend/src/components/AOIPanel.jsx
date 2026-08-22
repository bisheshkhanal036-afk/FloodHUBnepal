// AOI selection: "Draw area" (click-drag a rectangle on the map, handled
// by MapView) vs "Select basin" (fetch GET /api/basins once, click a
// polygon on the map). This panel owns the tab toggle, the basins fetch
// (triggered lazily -- only once the user actually opens this tab, so
// "Draw area" never waits on it), and the area-cap / selection summary
// text; MapView owns the actual map-canvas drawing/click interactions.
import { useEffect } from 'react'
import { listBasins } from '../api/client'
import { AREA_CAP_KM2 } from '../lib/geo'
import { SUPPORT_STATUS_COLORS, SUPPORT_STATUS_LABELS } from '../lib/colorRamp'
import { useAppState } from '../state/AppStateContext'

export default function AOIPanel() {
  const { state, dispatch } = useAppState()

  useEffect(() => {
    if (state.aoiMode !== 'basin' || state.basins.status !== 'idle') return
    dispatch({ type: 'BASINS_LOADING' })
    listBasins()
      .then((data) => dispatch({ type: 'BASINS_LOADED', data }))
      .catch((error) => dispatch({ type: 'BASINS_ERROR', error }))
  }, [state.aoiMode, state.basins.status, dispatch])

  return (
    <div className="aoi-panel">
      <div className="mode-toggle">
        <button
          type="button"
          className={`mode-toggle__button ${state.aoiMode === 'draw' ? 'mode-toggle__button--active' : ''}`}
          onClick={() => dispatch({ type: 'SET_AOI_MODE', mode: 'draw' })}
        >
          Draw area
        </button>
        <button
          type="button"
          className={`mode-toggle__button ${state.aoiMode === 'basin' ? 'mode-toggle__button--active' : ''}`}
          onClick={() => dispatch({ type: 'SET_AOI_MODE', mode: 'basin' })}
        >
          Select basin
        </button>
      </div>

      {state.aoiMode === 'draw' && (
        <p className="panel__hint">Click and drag on the map to draw a rectangular area (max {AREA_CAP_KM2} km²).</p>
      )}
      {state.aoiMode === 'basin' && (
        <>
          {state.basins.status === 'loading' && <p className="panel__hint">Loading basins (~3.9 MB)…</p>}
          {state.basins.status === 'error' && (
            <p className="field-error">{state.basins.error?.message || 'Could not load basins.'}</p>
          )}
          {state.basins.status === 'loaded' && (
            <>
              <p className="panel__hint">Click a basin on the map to select it as the AOI.</p>
              <ul className="legend legend--inline">
                {Object.entries(SUPPORT_STATUS_LABELS).map(([status, label]) => (
                  <li key={status}>
                    <span className="legend__swatch" style={{ background: SUPPORT_STATUS_COLORS[status] }} />
                    {label}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}

      {state.areaWarning && <p className="field-error">{state.areaWarning}</p>}

      {state.aoi && (
        <div className="aoi-summary">
          <strong>AOI set</strong> ({state.aoi.source === 'basin' ? `basin ${state.aoi.basinId}` : 'drawn area'})
          <div className="aoi-summary__bbox">
            bbox: [{state.aoi.bbox.map((v) => v.toFixed(4)).join(', ')}]
          </div>
          <button type="button" className="link-button" onClick={() => dispatch({ type: 'CLEAR_AOI' })}>
            Clear AOI
          </button>
        </div>
      )}
    </div>
  )
}
