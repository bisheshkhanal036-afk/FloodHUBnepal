// AOI selection: "Draw area" (click-drag a rectangle on the map, handled
// by MapView) vs "Select basin" (fetch GET /api/basins once per level,
// click a polygon on the map) vs "Select district" (fetch GET
// /api/districts once, click a polygon on the map). This panel owns the
// tab toggle, the basin-level toggle, the basins/districts fetches
// (each triggered lazily -- only once the user actually opens that tab,
// so "Draw area" never waits on either), and the area-cap / selection
// summary text; MapView owns the actual map-canvas drawing/click
// interactions.
import { useEffect } from 'react'
import { listBasins, listDistricts } from '../api/client'
import { AREA_CAP_KM2 } from '../lib/geo'
import { SUPPORT_STATUS_COLORS, SUPPORT_STATUS_LABELS, DISTRICT_FILL_COLOR } from '../lib/colorRamp'
import { useAppState } from '../state/AppStateContext'
import ErrorNotice from './ErrorNotice'

export default function AOIPanel() {
  const { state, dispatch } = useAppState()

  function loadBasins() {
    dispatch({ type: 'BASINS_LOADING' })
    listBasins(state.basinLevel)
      .then((data) => dispatch({ type: 'BASINS_LOADED', data }))
      .catch((error) => dispatch({ type: 'BASINS_ERROR', error }))
  }

  function loadDistricts() {
    dispatch({ type: 'DISTRICTS_LOADING' })
    listDistricts()
      .then((data) => dispatch({ type: 'DISTRICTS_LOADED', data }))
      .catch((error) => dispatch({ type: 'DISTRICTS_ERROR', error }))
  }

  useEffect(() => {
    if (state.aoiMode !== 'basin' || state.basins.status !== 'idle') return
    loadBasins()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadBasins reads state.basinLevel fresh each call; the retry button below calls it directly instead of going through this effect
  }, [state.aoiMode, state.basinLevel, state.basins.status, dispatch])

  useEffect(() => {
    if (state.aoiMode !== 'district' || state.districts.status !== 'idle') return
    loadDistricts()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the retry button below calls loadDistricts directly instead of going through this effect
  }, [state.aoiMode, state.districts.status, dispatch])

  return (
    <div className="aoi-panel">
      <div className="mode-toggle mode-toggle--triple">
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
        <button
          type="button"
          className={`mode-toggle__button ${state.aoiMode === 'district' ? 'mode-toggle__button--active' : ''}`}
          onClick={() => dispatch({ type: 'SET_AOI_MODE', mode: 'district' })}
        >
          Select district
        </button>
      </div>

      {state.aoiMode === 'draw' && (
        <p className="panel__hint">Click and drag on the map to draw a rectangular area (max {AREA_CAP_KM2} km²).</p>
      )}
      {state.aoiMode === 'basin' && (
        <>
          <div className="mode-toggle mode-toggle--sub">
            <button
              type="button"
              className={`mode-toggle__button ${state.basinLevel === 8 ? 'mode-toggle__button--active' : ''}`}
              onClick={() => state.basinLevel !== 8 && dispatch({ type: 'SET_BASIN_LEVEL', level: 8 })}
            >
              Level 8 (coarser)
            </button>
            <button
              type="button"
              className={`mode-toggle__button ${state.basinLevel === 9 ? 'mode-toggle__button--active' : ''}`}
              onClick={() => state.basinLevel !== 9 && dispatch({ type: 'SET_BASIN_LEVEL', level: 9 })}
            >
              Level 9 (finer)
            </button>
          </div>
          {state.basins.status === 'loading' && <p className="panel__hint">Loading basins…</p>}
          {state.basins.status === 'error' && (
            <ErrorNotice error={state.basins.error} fallback="Could not load basins." onRetry={loadBasins} />
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
      {state.aoiMode === 'district' && (
        <>
          {state.districts.status === 'loading' && <p className="panel__hint">Loading districts…</p>}
          {state.districts.status === 'error' && (
            <ErrorNotice error={state.districts.error} fallback="Could not load districts." onRetry={loadDistricts} />
          )}
          {state.districts.status === 'loaded' && (
            <>
              <p className="panel__hint">Click one of Nepal's 77 districts on the map to select it as the AOI.</p>
              <ul className="legend legend--inline">
                <li>
                  <span className="legend__swatch" style={{ background: DISTRICT_FILL_COLOR }} />
                  District
                </li>
              </ul>
            </>
          )}
        </>
      )}

      {state.areaWarning && <p className="field-error">{state.areaWarning}</p>}

      {state.aoi && (
        <div className="aoi-summary">
          <strong>AOI set</strong> (
          {state.aoi.source === 'basin'
            ? `basin ${state.aoi.basinId} (level ${state.aoi.basinLevel})`
            : state.aoi.source === 'district'
              ? `district ${state.aoi.districtPcode}`
              : 'drawn area'}
          )
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
