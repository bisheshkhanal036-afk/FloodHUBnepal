"""Unit tests for the two-level cluster/criteria composition in
app/ahp/hierarchy.py.
"""

from __future__ import annotations

import pytest

from app.ahp.constants import CANONICAL_CLUSTERS
from app.ahp.errors import AHPConsistencyError, AHPValidationError
from app.ahp.hierarchy import compute_hierarchy

# A perfectly consistent 5x5 cluster matrix built from known weights, so
# the composition arithmetic below can be checked against exact expected
# numbers rather than needing its own literature citation — the
# eigenvector math itself is already verified against real published
# matrices in test_ahp_core.py.
_CLUSTER_WEIGHTS = [5.0, 3.0, 2.0, 1.0, 1.0]


def _consistent_matrix(weights: list[float]) -> list[list[float]]:
    n = len(weights)
    return [[weights[i] / weights[j] for j in range(n)] for i in range(n)]


def _cluster_comparison():
    return {"items": list(CANONICAL_CLUSTERS), "matrix": _consistent_matrix(_CLUSTER_WEIGHTS)}


def test_final_weights_equal_cluster_weight_times_within_weight():
    cluster_comparison = _cluster_comparison()
    topo_weights = [3.0, 1.0]
    hydro_weights = [2.0, 2.0, 1.0]
    within_cluster_comparisons = {
        "Topographic": {"items": ["slope", "elevation"], "matrix": _consistent_matrix(topo_weights)},
        "Hydrological": {
            "items": ["dist_to_river", "twi", "drainage_density"],
            "matrix": _consistent_matrix(hydro_weights),
        },
    }

    result = compute_hierarchy(cluster_comparison, within_cluster_comparisons)

    cluster_total = sum(_CLUSTER_WEIGHTS)
    topo_cluster_weight = _CLUSTER_WEIGHTS[0] / cluster_total  # "Topographic" is index 0
    hydro_cluster_weight = _CLUSTER_WEIGHTS[1] / cluster_total  # "Hydrological" is index 1
    topo_total = sum(topo_weights)
    hydro_total = sum(hydro_weights)

    assert result.final_weights["slope"] == pytest.approx(
        topo_cluster_weight * (topo_weights[0] / topo_total), abs=1e-9
    )
    assert result.final_weights["elevation"] == pytest.approx(
        topo_cluster_weight * (topo_weights[1] / topo_total), abs=1e-9
    )
    assert result.final_weights["dist_to_river"] == pytest.approx(
        hydro_cluster_weight * (hydro_weights[0] / hydro_total), abs=1e-9
    )
    # Only 2 of 5 clusters supplied: final weights need not sum to 1, and
    # the result must say so explicitly rather than let a caller assume
    # this partial set is normalized.
    assert sum(result.final_weights.values()) == pytest.approx(
        topo_cluster_weight + hydro_cluster_weight, abs=1e-9
    )
    assert result.complete is False
    assert result.missing_clusters == ["Land Use", "Infrastructure", "Exposure"]


def test_final_weights_sum_to_one_when_all_clusters_supplied():
    cluster_comparison = _cluster_comparison()
    within_cluster_comparisons = {
        cluster: {"items": [f"{cluster}_a", f"{cluster}_b"], "matrix": _consistent_matrix([2.0, 1.0])}
        for cluster in CANONICAL_CLUSTERS
    }

    result = compute_hierarchy(cluster_comparison, within_cluster_comparisons)

    assert sum(result.final_weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert result.complete is True
    assert result.missing_clusters == []


def test_rejects_cluster_comparison_with_wrong_items():
    cluster_comparison = {
        "items": ["Topographic", "Hydrological", "Land Use", "Infrastructure", "NotACluster"],
        "matrix": _consistent_matrix(_CLUSTER_WEIGHTS),
    }

    with pytest.raises(AHPValidationError):
        compute_hierarchy(cluster_comparison, {})


def test_rejects_unknown_within_cluster_key():
    with pytest.raises(AHPValidationError):
        compute_hierarchy(
            _cluster_comparison(),
            {"NotACluster": {"items": ["a", "b"], "matrix": _consistent_matrix([1.0, 1.0])}},
        )


def test_raises_consistency_error_when_a_within_cluster_matrix_is_inconsistent():
    """Reuses the Saaty (2003) house-buying matrix (see test_ahp_core.py)
    as a real, known-inconsistent (CR=0.17) within-cluster matrix to
    verify hierarchy composition rejects the whole request rather than
    silently composing final weights on top of an invalid input.
    """
    inconsistent_items = ["Size", "Trans", "Nbrhd", "Age", "Yard", "Modern", "Cond", "Finance"]
    inconsistent_matrix = [
        [1, 5, 3, 7, 6, 6, 1 / 3, 1 / 4],
        [1 / 5, 1, 1 / 3, 5, 3, 3, 1 / 5, 1 / 7],
        [1 / 3, 3, 1, 6, 3, 4, 6, 1 / 5],
        [1 / 7, 1 / 5, 1 / 6, 1, 1 / 3, 1 / 4, 1 / 7, 1 / 8],
        [1 / 6, 1 / 3, 1 / 3, 3, 1, 1 / 2, 1 / 5, 1 / 6],
        [1 / 6, 1 / 3, 1 / 4, 4, 2, 1, 1 / 5, 1 / 6],
        [3, 5, 1 / 6, 7, 5, 5, 1, 1 / 2],
        [4, 7, 5, 8, 6, 6, 2, 1],
    ]

    with pytest.raises(AHPConsistencyError) as exc_info:
        compute_hierarchy(
            _cluster_comparison(),
            {"Topographic": {"items": inconsistent_items, "matrix": inconsistent_matrix}},
        )

    failure = exc_info.value.failures[0]
    assert failure["matrix"] == "Topographic"
    assert failure["consistency_ratio"] >= 0.10
    assert len(failure["worst_pairs"]) > 0
