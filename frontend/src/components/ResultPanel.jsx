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
import { RISK_LEGEND_STOPS } from '../lib/colorRamp'
import { useAppState } from '../state/AppStateContext'
import ReclassificationTable from './ReclassificationTable'

export default function ResultPanel() {
  const { state } = useAppState()
  const { result, criteriaUsed, weightsUsed } = state.overlay
  if (!result) return null

  return (
    <div className="result-panel">
      <h4>Risk surface</h4>

      <p className="field-warning">
        The reclassification breakdown below uses this app's built-in default thresholds — placeholder,
        equal-interval breaks, not sourced from flood-risk literature or calibrated against real Kathmandu Valley
        data. Treat the resulting risk surface as illustrative of the pipeline, not as a validated assessment.
      </p>

      <div className="legend legend--ramp">
        <div className="legend__ramp-bar">
          {RISK_LEGEND_STOPS.map((stop) => (
            <span key={stop.value} style={{ background: stop.color, flex: 1 }} />
          ))}
        </div>
        <div className="legend__ramp-labels">
          <span>0.0 (low risk)</span>
          <span>1.0 (high risk)</span>
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
