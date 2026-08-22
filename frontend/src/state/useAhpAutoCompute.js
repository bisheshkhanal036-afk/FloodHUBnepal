// Debounced "call POST /api/ahp/compute live as values change" behavior
// (per the brief), factored out of AHPPanel so the component itself
// stays declarative. Cancels/ignores stale in-flight responses via a
// monotonically increasing request id, so a fast edit followed by
// another edit can never have the first (now-outdated) response
// overwrite the second's.
import { useEffect, useRef } from 'react'
import { computeAHP } from '../api/client'
import { CANONICAL_CLUSTERS } from '../config/criteria'
import { useAppState } from './AppStateContext'

const DEBOUNCE_MS = 400

export function useAhpAutoCompute() {
  const { state, dispatch } = useAppState()
  const requestIdRef = useRef(0)

  const { weightMode, ahpMatrices, criteriaEnabled } = state
  const clusterMatrixKey = JSON.stringify(ahpMatrices.cluster.matrix)
  const withinClusterKey = JSON.stringify(
    CANONICAL_CLUSTERS.map((c) => [c, ahpMatrices.withinCluster[c]?.items, ahpMatrices.withinCluster[c]?.matrix])
  )
  const criteriaKey = JSON.stringify(criteriaEnabled)

  useEffect(() => {
    if (weightMode !== 'ahp') return
    // Nothing to compare yet (no criterion checked in any cluster) --
    // don't call the endpoint just to get an all-empty, all-missing
    // response back.
    if (Object.keys(ahpMatrices.withinCluster).length === 0) return

    const thisRequestId = ++requestIdRef.current
    dispatch({ type: 'AHP_LOADING' })

    const timer = setTimeout(async () => {
      const payload = {
        cluster_comparison: { items: [...ahpMatrices.cluster.items], matrix: ahpMatrices.cluster.matrix },
        within_cluster_comparisons: Object.fromEntries(
          Object.entries(ahpMatrices.withinCluster).map(([cluster, m]) => [
            cluster,
            { items: m.items, matrix: m.matrix },
          ])
        ),
      }
      try {
        const result = await computeAHP(payload)
        if (requestIdRef.current === thisRequestId) dispatch({ type: 'AHP_LOADED', result })
      } catch (error) {
        if (requestIdRef.current === thisRequestId) dispatch({ type: 'AHP_ERROR', error })
      }
    }, DEBOUNCE_MS)

    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on stable JSON snapshots instead
  }, [weightMode, clusterMatrixKey, withinClusterKey, criteriaKey, dispatch])
}
