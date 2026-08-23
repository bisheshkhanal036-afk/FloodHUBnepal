// The vulnerability-classification / computation report: a heavier,
// optional follow-up to a successful compute (POST /api/overlay/report),
// showing hazard-class zonal stats, headline high-risk figures, and the
// weighting breakdown that produced the result. Gated on state.overlay
// being loaded -- this is display for an EXISTING result, not a new
// computation of its own.
import { useState } from 'react'
import { absoluteDataUrl, generateReport } from '../api/client'
import { CRITERIA_BY_ID } from '../config/criteria'
import { riskValueToCssColor } from '../lib/colorRamp'
import { useAppState } from '../state/AppStateContext'
import CriterionSnapshot from './CriterionSnapshot'

/** state.ahpMatrices already has exactly the {items, matrix} shape POST /api/overlay/report's weighting.cluster_comparison/within_cluster_comparisons expects -- built directly from the pairwise-comparison UI, not re-derived here. */
function buildWeightingPayload(state) {
  if (state.weightMode === 'ahp') {
    return {
      method: 'ahp',
      cluster_comparison: state.ahpMatrices.cluster,
      within_cluster_comparisons: state.ahpMatrices.withinCluster,
    }
  }
  return { method: state.weightMode } // 'equal' | 'manual'
}

/** The selected basin's support_status, looked up from the already-loaded basins GeoJSON by hybas_id -- not tracked as its own state field since the full feature list (which already carries it) is already in memory. */
function basinSupportStatus(state) {
  if (state.aoi?.source !== 'basin' || !state.aoi.basinId) return null
  const feature = state.basins.data?.features?.find((f) => f.properties.hybas_id === state.aoi.basinId)
  return feature?.properties.support_status ?? null
}

function formatPct(value) {
  return `${value.toFixed(1)}%`
}

function formatNumber(value) {
  return Math.round(value).toLocaleString()
}

export default function ReportPanel() {
  const { state, dispatch } = useAppState()
  // Which criterion's snapshot <details> is open, by id -- CriterionSnapshot
  // is only mounted (and only then fetches+decodes) while its own entry
  // is open, so generating a report with many criteria never decodes
  // rasters nobody actually looks at. Declared before the early return
  // below (React's rule: hooks must run unconditionally on every render
  // of this component instance).
  const [openSnapshotId, setOpenSnapshotId] = useState(null)
  const { criteriaUsed, weightsUsed } = state.overlay
  if (state.overlay.status !== 'loaded' || !criteriaUsed || !weightsUsed) return null

  const { status, result, error } = state.report

  async function handleGenerateReport() {
    dispatch({ type: 'REPORT_LOADING' })
    try {
      const payload = {
        aoi: { bbox: state.aoi.bbox, polygon: state.aoi.polygon || null },
        criteria: criteriaUsed.map((c) => ({
          id: c.id,
          source: c.source,
          reclassification_rules: c.reclassification_rules,
          name: CRITERIA_BY_ID[c.id]?.label,
          // Carried over from the exact snapshot ComputePanel submitted --
          // drainage_density/hand's shared stream-network override, when
          // set, so the report's own risk-surface computation (reusing
          // POST /compute's cache by identical inputs) actually hits that
          // cache instead of silently falling back to the default
          // threshold and computing something different.
          stream_threshold_cells: c.stream_threshold_cells,
        })),
        final_weights: weightsUsed,
        complete: true,
        weighting: buildWeightingPayload(state),
        hybas_id: state.aoi.source === 'basin' ? state.aoi.basinId : null,
        support_status: basinSupportStatus(state),
      }
      const reportResult = await generateReport(payload)
      dispatch({ type: 'REPORT_LOADED', result: reportResult })
    } catch (err) {
      dispatch({ type: 'REPORT_ERROR', error: err })
    }
  }

  return (
    <div className="report-panel">
      <button
        type="button"
        className="compute-button report-panel__generate-button"
        disabled={status === 'loading'}
        onClick={handleGenerateReport}
      >
        {status === 'loading' ? 'Generating report…' : result ? 'Regenerate report' : 'Generate report'}
      </button>
      {status === 'loading' && (
        <p className="panel__hint">
          Building the full report — classifying every building in the AOI against the hazard surface, which takes
          longer than the risk surface itself.
        </p>
      )}
      {status === 'error' && <p className="field-error">{error?.message || 'Report generation failed.'}</p>}

      {result && (
        <div className="report-panel__result">
          <div className="report-panel__downloads">
            <a href={absoluteDataUrl(result.risk_surface_data_url)} className="result-panel__download-link">
              Download risk surface (.tif)
            </a>
            <a href={absoluteDataUrl(result.hazard_classes_data_url)} className="result-panel__download-link">
              Download hazard classes (.tif)
            </a>
          </div>

          <div className="report-panel__headline">
            <div className="report-panel__stat">
              <span className="report-panel__stat-value">{formatNumber(result.total_buildings)}</span>
              <span className="report-panel__stat-label">buildings classified</span>
            </div>
            <div className="report-panel__stat report-panel__stat--high-risk">
              <span className="report-panel__stat-value">
                {formatNumber(result.high_risk_building_count)} ({formatPct(result.high_risk_building_pct)})
              </span>
              <span className="report-panel__stat-label">buildings in High + Very High zones</span>
            </div>
            <div className="report-panel__stat report-panel__stat--high-risk">
              <span className="report-panel__stat-value">
                {formatNumber(result.high_risk_population)} ({formatPct(result.high_risk_population_pct)})
              </span>
              <span className="report-panel__stat-label">people in High + Very High zones</span>
            </div>
            <div className="report-panel__stat">
              <span className="report-panel__stat-value">{result.total_area_km2.toFixed(2)} km²</span>
              <span className="report-panel__stat-label">area with a valid hazard class</span>
            </div>
          </div>

          <table className="report-panel__zonal-table">
            <thead>
              <tr>
                <th>Hazard class</th>
                <th>Area (km²)</th>
                <th>Population</th>
                <th>Buildings</th>
              </tr>
            </thead>
            <tbody>
              {result.zonal_stats.map((s) => (
                <tr key={s.hazard_class} className={`report-panel__zonal-row report-panel__zonal-row--class-${s.hazard_class}`}>
                  <td>
                    <span className="report-panel__zonal-row__label">
                      <span
                        className="legend__swatch"
                        style={{ background: riskValueToCssColor((s.hazard_class - 1) / 4) }}
                      />
                      {s.hazard_label}
                    </span>
                  </td>
                  <td>{s.area_km2.toFixed(3)}</td>
                  <td>{formatNumber(s.population)}</td>
                  <td>{formatNumber(s.building_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="report-panel__weighting">
            <h5>Weighting used</h5>
            <p className="panel__hint">
              Method: <strong>{result.weighting.method}</strong>
            </p>
            {result.weighting.consistency_warning && (
              <p className="field-warning">{result.weighting.consistency_warning}</p>
            )}
            <div className="report-panel__criteria">
              {result.criteria.map((c) => {
                const isOpen = openSnapshotId === c.id
                return (
                  <details
                    key={c.id}
                    className="report-panel__criterion"
                    open={isOpen}
                    onToggle={(e) => setOpenSnapshotId(e.target.open ? c.id : null)}
                  >
                    <summary>
                      {c.name}
                      {c.cluster ? ` (${c.cluster})` : ''} —{' '}
                      {((result.weighting.final_weights[c.id] || 0) * 100).toFixed(1)}%
                    </summary>
                    {isOpen && (
                      <div className="report-panel__criterion-detail">
                        <CriterionSnapshot dataUrl={c.data_url} />
                        <a href={absoluteDataUrl(c.data_url)} className="result-panel__download-link">
                          Download {c.name} (.tif)
                        </a>
                      </div>
                    )}
                  </details>
                )
              })}
            </div>
          </div>

          {result.aoi.hybas_id && (
            <p className="panel__hint">
              Basin HYBAS_ID {result.aoi.hybas_id}
              {result.aoi.support_status ? ` (${result.aoi.support_status})` : ''}
            </p>
          )}

          <p className="panel__hint">Generated {new Date(result.generated_at).toLocaleString()}</p>
        </div>
      )}
    </div>
  )
}
