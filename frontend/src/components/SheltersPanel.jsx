// The sidebar's own "Shelters" step: identifies real OSM buildings in
// the AOI as candidate emergency-shelter sites (safety/accessibility/
// service-value suitability -- see backend/app/overlay/shelters.py's
// own docstring for the full methodology and its deliberate scope: a
// SITE-SUITABILITY ranking from existing building stock, not a
// classification of existing tagged shelters). Same
// gated-on-a-successful-compute / reuse-the-snapshot shape as
// ReportPanel.jsx, since a ranked list of ~20 candidates is compact
// enough to render directly in the sidebar rather than needing its own
// map-overlay infographic the way the full report does.
import { identifyShelterSites } from '../api/client'
import { useAppState } from '../state/AppStateContext'
import ErrorNotice from './ErrorNotice'

export default function SheltersPanel() {
  const { state, dispatch } = useAppState()
  const { criteriaUsed, weightsUsed } = state.overlay
  if (state.overlay.status !== 'loaded' || !criteriaUsed || !weightsUsed) return null

  const { status, result, error } = state.shelters

  async function handleIdentify() {
    // Same double-click/double-Enter guard ReportPanel's own
    // handleGenerateReport documents.
    if (status === 'loading') return
    dispatch({ type: 'SHELTERS_LOADING' })
    try {
      const payload = {
        aoi: { bbox: state.aoi.bbox, polygon: state.aoi.polygon || null },
        criteria: criteriaUsed.map((c) => ({
          id: c.id,
          source: c.source,
          reclassification_rules: c.reclassification_rules,
          // Same reasoning ReportPanel.jsx's own payload carries this
          // through: the exact same threshold override compute already
          // used, so this hits POST /compute's cache rather than
          // silently recomputing under the default threshold.
          stream_threshold_cells: c.stream_threshold_cells,
        })),
        final_weights: weightsUsed,
        complete: true,
      }
      const sheltersResult = await identifyShelterSites(payload)
      dispatch({ type: 'SHELTERS_LOADED', result: sheltersResult })
    } catch (err) {
      dispatch({ type: 'SHELTERS_ERROR', error: err })
    }
  }

  return (
    <div className="shelters-panel">
      <p className="panel__hint">
        Ranks large buildings in the AOI as candidate shelter sites — safe ground (outside the high/very-high hazard
        zones), close to a road, and near the people they'd serve. A site-suitability ranking from the AOI's own
        building stock, not a list of buildings already designated as shelters.
      </p>
      <button
        type="button"
        className="compute-button shelters-panel__identify-button"
        disabled={status === 'loading'}
        onClick={handleIdentify}
      >
        {status === 'loading' ? 'Identifying sites…' : result ? 'Re-identify sites' : 'Identify shelter sites'}
      </button>
      {status === 'error' && (
        <ErrorNotice error={error} fallback="Shelter identification failed." onRetry={handleIdentify} />
      )}

      {result && (
        <>
          <p className="panel__hint">
            {result.candidates.length} candidate{result.candidates.length === 1 ? '' : 's'} of {result.total_buildings_in_aoi}{' '}
            buildings in the AOI ({result.excluded_too_small} too small, {result.excluded_high_hazard} in a high-hazard
            zone{result.excluded_no_data ? `, ${result.excluded_no_data} with no data` : ''}).
          </p>
          <button type="button" className="link-button" onClick={() => dispatch({ type: 'TOGGLE_SHELTERS_LAYER' })}>
            {state.sheltersLayerVisible ? 'Hide on map' : 'Show on map'}
          </button>

          {result.candidates.length > 0 && (
            <ol className="shelters-panel__list">
              {result.candidates.map((c) => (
                <li key={c.rank} className="shelters-panel__item">
                  <span className="shelters-panel__rank">#{c.rank}</span>
                  <span className="shelters-panel__detail">
                    {Math.round(c.footprint_area_m2)} m² · hazard: {c.hazard_label} ·{' '}
                    {c.distance_to_road_m != null ? `${Math.round(c.distance_to_road_m)} m to road` : 'road distance unknown'}
                  </span>
                  <span className="shelters-panel__score">{(c.suitability_score * 100).toFixed(0)}%</span>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </div>
  )
}
