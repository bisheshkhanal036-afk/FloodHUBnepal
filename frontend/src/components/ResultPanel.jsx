// Legend + reclassification breakdown + attribution + per-criterion
// warnings for the most recently computed risk surface. The raster
// itself is rendered on the map by MapView -- this panel is the
// accompanying "how was this number produced" detail the brief asks
// for (both the licensing attribution, and how each raster was
// reclassified), read from state.overlay.criteriaUsed/weightsUsed --
// a snapshot of exactly what was submitted for *this* result, not the
// live (possibly since-changed) criteria/weighting panels.
import { absoluteDataUrl } from '../api/client'
import { CRITERIA_BY_ID } from '../config/criteria'
import { RISK_COLOR_SCHEMES, RISK_COLOR_SCHEME_LABELS, riskLegendStops } from '../lib/colorRamp'
import { useAppState } from '../state/AppStateContext'
import ReclassificationTable from './ReclassificationTable'

export default function ResultPanel() {
  const { state, dispatch } = useAppState()
  const { result, criteriaUsed, weightsUsed } = state.overlay
  if (!result) return null

  const legendStops = riskLegendStops(state.riskColorScheme)

  return (
    <div className="result-panel">
      <h4>Risk surface</h4>

      <p className="field-warning">
        The reclassification breakdown below uses this app's built-in default thresholds — placeholder,
        equal-interval breaks, not sourced from flood-risk literature or calibrated against real Kathmandu Valley
        data. Treat the resulting risk surface as illustrative of the pipeline, not as a validated assessment.
      </p>

      <label className="result-panel__visibility-toggle">
        <input
          type="checkbox"
          checked={state.riskSurfaceVisible}
          onChange={() => dispatch({ type: 'TOGGLE_RISK_SURFACE_VISIBLE' })}
        />
        Show risk surface on map
      </label>

      <div className="result-panel__scheme-picker">
        <label htmlFor="risk-color-scheme">Color scheme</label>
        <select
          id="risk-color-scheme"
          value={state.riskColorScheme}
          onChange={(e) => dispatch({ type: 'SET_RISK_COLOR_SCHEME', scheme: e.target.value })}
        >
          {RISK_COLOR_SCHEMES.map((scheme) => (
            <option key={scheme} value={scheme}>
              {RISK_COLOR_SCHEME_LABELS[scheme]}
            </option>
          ))}
        </select>
      </div>

      <div className="legend legend--ramp">
        <div
          className="legend__ramp-bar"
          style={{
            background: `linear-gradient(to right, ${legendStops.map((s) => `${s.color} ${s.value * 100}%`).join(', ')})`,
          }}
        />
        <div className="legend__ramp-ticks">
          {legendStops.map((stop) => (
            <span key={stop.value} className="legend__ramp-tick" style={{ left: `${stop.value * 100}%` }}>
              {stop.value.toFixed(2)}
            </span>
          ))}
        </div>
        <div className="legend__ramp-labels">
          <span>Low risk</span>
          <span>High risk</span>
        </div>
      </div>

      <div className="result-panel__downloads">
        <a href={absoluteDataUrl(result.data_url)} className="result-panel__download-link">
          Download risk surface (.tif)
        </a>
        <a href={absoluteDataUrl(result.hazard_classes_data_url)} className="result-panel__download-link">
          Download hazard classes (.tif)
        </a>
      </div>

      {result.source_warnings.length > 0 && (
        <div className="result-panel__warnings">
          {result.source_warnings.map((w) => (
            <p className="field-warning" key={w.criterion_id}>
              <strong>{w.criterion_id}:</strong> {w.message}
            </p>
          ))}
        </div>
      )}

      {criteriaUsed && (
        <div className="reclassification">
          <h5>How each raster was reclassified</h5>
          {criteriaUsed.map((c) => {
            const criterion = CRITERIA_BY_ID[c.id]
            return (
              <details className="reclassification__criterion" key={c.id}>
                <summary>
                  {criterion.label}
                  <span className="reclassification__weight">
                    {' '}
                    — weight {((weightsUsed?.[c.id] || 0) * 100).toFixed(1)}%
                  </span>
                </summary>
                <ReclassificationTable criterion={criterion} rules={c.reclassification_rules} />
              </details>
            )
          })}
        </div>
      )}

      <div className="attribution">
        <h5>Data attribution</h5>
        <ul>
          {result.attribution.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}
