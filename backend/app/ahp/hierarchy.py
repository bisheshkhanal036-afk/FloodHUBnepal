"""Two-level AHP hierarchy composition: 5 clusters at the top, and one
pairwise matrix per cluster comparing that cluster's own criteria — per
schemas/ahp_pairwise_matrix.schema.json.

    final_weight(criterion) = cluster_weight(criterion.cluster)
                               * within_cluster_weight(criterion)

using eigenvector_weights (the primary method) at both levels.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import CANONICAL_CLUSTERS
from .core import PairwiseResult, compute_priority_vector
from .errors import AHPConsistencyError, AHPValidationError


@dataclass(frozen=True)
class HierarchyResult:
    cluster_comparison: PairwiseResult
    within_cluster_comparisons: dict[str, PairwiseResult]
    final_weights: dict[str, float]
    complete: bool
    missing_clusters: list[str]


def _failure_detail(matrix_key: str, result: PairwiseResult) -> dict:
    return {
        "matrix": matrix_key,
        "items": result.items,
        "consistency_ratio": result.consistency_ratio,
        "threshold": 0.10,
        "worst_pairs": [
            {
                "item_i": p.item_i,
                "item_j": p.item_j,
                "judgment": p.judgment,
                "epsilon": p.epsilon,
            }
            for p in result.worst_pairs
        ],
    }


def compute_hierarchy(
    cluster_comparison: dict, within_cluster_comparisons: dict[str, dict]
) -> HierarchyResult:
    """Compute the full two-level hierarchy.

    `cluster_comparison` is {"items": [...5 cluster names...], "matrix": [[...]]}.
    `within_cluster_comparisons` is {cluster_name: {"items": [...criterion ids...], "matrix": [[...]]}}.

    Raises AHPValidationError for structural problems (wrong cluster
    names, an unknown cluster key, etc.) and AHPConsistencyError if any
    matrix — the cluster comparison or any within-cluster comparison —
    fails the CR < 0.10 check. On success, every matrix passed the check.

    `within_cluster_comparisons` may cover fewer than all 5 clusters
    (e.g. while a caller is still assembling criteria for the rest).
    That's allowed, but the result's `final_weights` then does not sum
    to 1 — HierarchyResult.complete is False in that case, with
    `missing_clusters` listing which clusters have no within-cluster
    matrix yet, so callers can't mistake a partial weight set for a
    normalized one.
    """
    cluster_items = cluster_comparison["items"]
    if sorted(cluster_items) != sorted(CANONICAL_CLUSTERS):
        raise AHPValidationError(
            f"cluster_comparison.items must be exactly the 5 canonical clusters "
            f"{list(CANONICAL_CLUSTERS)!r}; got {cluster_items!r}"
        )
    for cluster_name in within_cluster_comparisons:
        if cluster_name not in CANONICAL_CLUSTERS:
            raise AHPValidationError(
                f"within_cluster_comparisons key {cluster_name!r} is not one of the "
                f"5 canonical clusters {list(CANONICAL_CLUSTERS)!r}"
            )

    cluster_result = compute_priority_vector(cluster_comparison["matrix"], cluster_items)
    within_results = {
        cluster_name: compute_priority_vector(m["matrix"], m["items"])
        for cluster_name, m in within_cluster_comparisons.items()
    }

    failures = []
    if not cluster_result.consistent:
        failures.append(_failure_detail("cluster_comparison", cluster_result))
    for cluster_name, result in within_results.items():
        if not result.consistent:
            failures.append(_failure_detail(cluster_name, result))
    if failures:
        raise AHPConsistencyError(failures)

    cluster_weight_by_name = dict(zip(cluster_result.items, cluster_result.eigenvector_weights))

    final_weights: dict[str, float] = {}
    for cluster_name, result in within_results.items():
        cluster_weight = cluster_weight_by_name[cluster_name]
        for criterion_id, within_weight in zip(result.items, result.eigenvector_weights):
            final_weights[criterion_id] = cluster_weight * within_weight

    missing_clusters = [c for c in CANONICAL_CLUSTERS if c not in within_results]

    return HierarchyResult(
        cluster_comparison=cluster_result,
        within_cluster_comparisons=within_results,
        final_weights=final_weights,
        complete=not missing_clusters,
        missing_clusters=missing_clusters,
    )
