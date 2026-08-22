// The full AHP customization UI: the always-present top-level 5-cluster
// comparison, plus one within-cluster comparison per cluster that has
// 2+ selected criteria (a cluster with exactly 1 selected criterion gets
// weight 1.0 automatically -- no comparison needed; a cluster with 0
// selected criteria just doesn't participate -- see AppStateContext's
// useFinalWeights for why that's fine: this app only requires every
// *selected* criterion's own cluster to be resolved, not all 5). Calls
// POST /api/ahp/compute live via useAhpAutoCompute as values change.
import { CANONICAL_CLUSTERS, criteriaByCluster } from '../config/criteria'
import { useAppState, useSelectedCriteriaIds } from '../state/AppStateContext'
import { useAhpAutoCompute } from '../state/useAhpAutoCompute'
import PairwiseMatrixEditor from './PairwiseMatrixEditor'

const CLUSTER_LABELS = Object.fromEntries(CANONICAL_CLUSTERS.map((c) => [c, c]))

function ConsistencyBadge({ consistencyRatio, consistent }) {
  return (
    <span className={`cr-badge ${consistent ? 'cr-badge--ok' : 'cr-badge--bad'}`}>
      CR = {consistencyRatio.toFixed(3)} {consistent ? '(consistent)' : '(≥ 0.10 — inconsistent)'}
    </span>
  )
}

function WeightsList({ items, labels, weights }) {
  return (
    <ul className="weights-list">
      {items.map((id, i) => (
        <li key={id}>
          <span>{labels[id] || id}</span>
          <span className="weights-list__value">{(weights[i] * 100).toFixed(1)}%</span>
        </li>
      ))}
    </ul>
  )
}

export default function AHPPanel() {
  useAhpAutoCompute()
  const { state, dispatch } = useAppState()
  const selectedIds = useSelectedCriteriaIds()
  const byCluster = criteriaByCluster()
  const { ahpMatrices, ahp } = state

  const failuresByMatrix = ahp.status === 'error' ? Object.fromEntries((ahp.error?.failures || []).map((f) => [f.matrix, f])) : {}
  const clusterResult = ahp.result?.cluster_comparison

  return (
    <div className="ahp-panel">
      {ahp.status === 'error' && !ahp.error?.failures && (
        <p className="field-error">{ahp.error?.message || 'AHP computation failed.'}</p>
      )}

      <div className="ahp-section">
        <h4>Cluster importance</h4>
        <p className="ahp-section__hint">How important is each hazard dimension, relative to the others?</p>
        <PairwiseMatrixEditor
          items={ahpMatrices.cluster.items}
          labels={CLUSTER_LABELS}
          matrix={ahpMatrices.cluster.matrix}
          onChange={(matrix) => dispatch({ type: 'SET_CLUSTER_PAIRWISE', matrix })}
        />
        {failuresByMatrix.cluster_comparison && (
          <ConsistencyBadge consistencyRatio={failuresByMatrix.cluster_comparison.consistency_ratio} consistent={false} />
        )}
        {clusterResult && <ConsistencyBadge consistencyRatio={clusterResult.consistency_ratio} consistent={clusterResult.consistent} />}
        {clusterResult && (
          <WeightsList items={clusterResult.items} labels={CLUSTER_LABELS} weights={clusterResult.eigenvector_weights} />
        )}
      </div>

      {CANONICAL_CLUSTERS.map((cluster) => {
        const clusterCriteria = byCluster[cluster]
        const checkedInCluster = clusterCriteria.filter((c) => selectedIds.includes(c.id))
        const labels = Object.fromEntries(clusterCriteria.map((c) => [c.id, c.label]))
        const withinResult = ahp.result?.within_cluster_comparisons?.[cluster]
        const failure = failuresByMatrix[cluster]

        return (
          <div className="ahp-section" key={cluster}>
            <h4>{cluster}</h4>
            {checkedInCluster.length === 0 && (
              <p className="ahp-section__hint">
                No criteria selected in this cluster — it won't be part of the weighting.
              </p>
            )}
            {checkedInCluster.length === 1 && (
              <p className="ahp-section__hint">
                Only "{checkedInCluster[0].label}" is selected — it automatically gets weight 1.0 within this
                cluster.
              </p>
            )}
            {checkedInCluster.length >= 2 && ahpMatrices.withinCluster[cluster] && (
              <>
                <PairwiseMatrixEditor
                  items={ahpMatrices.withinCluster[cluster].items}
                  labels={labels}
                  matrix={ahpMatrices.withinCluster[cluster].matrix}
                  onChange={(matrix) => dispatch({ type: 'SET_WITHIN_CLUSTER_PAIRWISE', cluster, matrix })}
                />
                {failure && <ConsistencyBadge consistencyRatio={failure.consistency_ratio} consistent={false} />}
                {withinResult && <ConsistencyBadge consistencyRatio={withinResult.consistency_ratio} consistent={withinResult.consistent} />}
                {withinResult && (
                  <WeightsList items={withinResult.items} labels={labels} weights={withinResult.eigenvector_weights} />
                )}
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}
