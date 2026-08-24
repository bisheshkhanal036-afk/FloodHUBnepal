// The full vulnerability report, rendered as an infographic-style
// overlay covering the map area (see App.jsx/.map-area) rather than
// stacked into the sidebar -- ReportPanel.jsx (the sidebar's own step 5)
// stays a compact Generate/Show-Hide trigger; this component owns
// everything the generated report actually shows: headline stat tiles,
// a population-by-hazard-class bar chart, the zonal table, the
// weighting breakdown with per-criterion snapshots, and the download
// links. Toggled via state.reportOverlayVisible (ReportPanel's button,
// or this component's own close button); auto-shown once a report
// finishes generating (REPORT_LOADED).
import { useState } from 'react'
import { absoluteDataUrl } from '../api/client'
import { riskValueToCssColor } from '../lib/colorRamp'
import { useAppState } from '../state/AppStateContext'
import CriterionSnapshot from './CriterionSnapshot'

function formatPct(value) {
  return `${value.toFixed(1)}%`
}

function formatNumber(value) {
  return Math.round(value).toLocaleString()
}

/** Horizontal bar chart: population per hazard class. One measure (population, the
 * most vulnerability-relevant of the three the zonal table already carries) rather
 * than three competing scales on one axis -- area_km2/building_count stay in the
 * table below instead of a second/third bar group, per the "never a dual-axis
 * chart" rule (dataviz skill). Each bar is directly labeled (class name + value),
 * so no separate legend box is needed -- identity is never color-alone, since the
 * same swatch color already keys the zonal table's own rows. */
function HazardPopulationChart({ zonalStats }) {
  const maxPopulation = Math.max(1, ...zonalStats.map((s) => s.population))
  return (
    <div className="report-overlay__chart" role="img" aria-label="Population by hazard class">
      {zonalStats.map((s) => {
        const color = riskValueToCssColor((s.hazard_class - 1) / 4)
        const widthPct = (s.population / maxPopulation) * 100
        return (
          <div className="report-overlay__chart-row" key={s.hazard_class} title={`${s.hazard_label}: ${formatNumber(s.population)} people`}>
            <span className="report-overlay__chart-label">{s.hazard_label}</span>
            <div className="report-overlay__chart-track">
              <div className="report-overlay__chart-bar" style={{ width: `${widthPct}%`, background: color }} />
            </div>
            <span className="report-overlay__chart-value">{formatNumber(s.population)}</span>
          </div>
        )
      })}
    </div>
  )
}

export default function ReportOverlay() {
  const { state, dispatch } = useAppState()
  const [openSnapshotId, setOpenSnapshotId] = useState(null)
  const { result } = state.report

  if (state.overlay.status !== 'loaded' || !result || !state.reportOverlayVisible) return null

  return (
    <div className="report-overlay">
      <div className="report-overlay__panel">
        <header className="report-overlay__header">
          <h3>Vulnerability report</h3>
          <button
            type="button"
            className="report-overlay__close"
            onClick={() => dispatch({ type: 'TOGGLE_REPORT_OVERLAY' })}
            aria-label="Hide report"
            title="Hide report"
          >
            ×
          </button>
        </header>

        <div className="report-overlay__body">
          <div className="report-overlay__downloads">
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

          <h5 className="report-overlay__section-heading">Population by hazard class</h5>
          <HazardPopulationChart zonalStats={result.zonal_stats} />

          <h5 className="report-overlay__section-heading">Zonal breakdown</h5>
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
      </div>
    </div>
  )
}
