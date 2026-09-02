// The sidebar's own "5. Vulnerability report" step: just the trigger
// (Generate/Regenerate report button, loading/error state) plus a
// "Show report" / "Hide report" toggle once one exists. The actual
// report content -- headline stats, hazard-class chart, zonal table,
// weighting breakdown, per-criterion snapshots -- lives in
// ReportOverlay.jsx instead, absolutely positioned over the map (see
// App.jsx), specifically so this step doesn't reintroduce the crowded-
// sidebar problem that split caused in the first place. Gated on
// state.overlay being loaded -- this is a follow-up to an EXISTING
// result, not a new computation of its own.
import { generateReport } from '../api/client'
import { CRITERIA_BY_ID } from '../config/criteria'
import { useAppState } from '../state/AppStateContext'
import ErrorNotice from './ErrorNotice'

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

export default function ReportPanel() {
  const { state, dispatch } = useAppState()
  const { criteriaUsed, weightsUsed } = state.overlay
  if (state.overlay.status !== 'loaded' || !criteriaUsed || !weightsUsed) return null

  const { status, result, error } = state.report

  async function handleGenerateReport() {
    // Guards the same request the button's own `disabled={status ===
    // 'loading'}` already blocks, in case the handler fires again before
    // that re-render lands (a fast double-click/double-Enter) -- the
    // same belt-and-suspenders shape ComputePanel's own handleCompute
    // already uses (`if (disabled) return`).
    if (status === 'loading') return
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
      {status === 'error' && (
        <ErrorNotice error={error} fallback="Report generation failed." onRetry={handleGenerateReport} />
      )}

      {result && (
        <>
          <p className="panel__hint">Report ready — shown as an overlay on the map.</p>
          <button type="button" className="link-button" onClick={() => dispatch({ type: 'TOGGLE_REPORT_OVERLAY' })}>
            {state.reportOverlayVisible ? 'Hide report' : 'Show report'}
          </button>
        </>
      )}
    </div>
  )
}
