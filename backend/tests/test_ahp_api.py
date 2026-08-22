"""Tests for POST /api/ahp/compute end to end, via FastAPI's TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ahp.constants import CANONICAL_CLUSTERS
from app.main import app

client = TestClient(app)


def _consistent_matrix(weights: list[float]) -> list[list[float]]:
    n = len(weights)
    return [[weights[i] / weights[j] for j in range(n)] for i in range(n)]


def test_compute_endpoint_returns_final_weights_for_valid_request():
    payload = {
        "cluster_comparison": {
            "items": list(CANONICAL_CLUSTERS),
            "matrix": _consistent_matrix([5.0, 3.0, 2.0, 1.0, 1.0]),
        },
        "within_cluster_comparisons": {
            "Topographic": {"items": ["slope", "elevation"], "matrix": _consistent_matrix([3.0, 1.0])},
        },
    }

    response = client.post("/api/ahp/compute", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["cluster_comparison"]["consistent"] is True
    assert body["within_cluster_comparisons"]["Topographic"]["consistent"] is True

    cluster_weight = 5.0 / 12.0  # Topographic is index 0 of [5,3,2,1,1], sum=12
    within_weight = 3.0 / 4.0
    assert body["final_weights"]["slope"] == pytest.approx(cluster_weight * within_weight, abs=1e-6)
    assert body["final_weights"]["elevation"] == pytest.approx(cluster_weight * (1.0 / 4.0), abs=1e-6)

    # Only 1 of 5 clusters was supplied, so the response must say the
    # weight set is incomplete rather than let a caller silently treat
    # it as a normalized final answer.
    assert body["complete"] is False
    assert body["missing_clusters"] == ["Hydrological", "Land Use", "Infrastructure", "Exposure"]


def test_compute_endpoint_marks_complete_when_all_clusters_supplied():
    payload = {
        "cluster_comparison": {
            "items": list(CANONICAL_CLUSTERS),
            "matrix": _consistent_matrix([5.0, 3.0, 2.0, 1.0, 1.0]),
        },
        "within_cluster_comparisons": {
            cluster: {"items": [f"{cluster}_a", f"{cluster}_b"], "matrix": _consistent_matrix([2.0, 1.0])}
            for cluster in CANONICAL_CLUSTERS
        },
    }

    response = client.post("/api/ahp/compute", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["complete"] is True
    assert body["missing_clusters"] == []
    assert sum(body["final_weights"].values()) == pytest.approx(1.0, abs=1e-6)


def test_compute_endpoint_rejects_inconsistent_matrix_with_worst_pairs():
    """Reuses the Saaty (2003) house-buying matrix (CR=0.17) as the
    'Topographic' within-cluster matrix — see test_ahp_core.py for the
    citation and independent verification of its published numbers.
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
    payload = {
        "cluster_comparison": {
            "items": list(CANONICAL_CLUSTERS),
            "matrix": _consistent_matrix([5.0, 3.0, 2.0, 1.0, 1.0]),
        },
        "within_cluster_comparisons": {
            "Topographic": {"items": inconsistent_items, "matrix": inconsistent_matrix},
        },
    }

    response = client.post("/api/ahp/compute", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "ahp_consistency_check_failed"
    failure = detail["failures"][0]
    assert failure["matrix"] == "Topographic"
    assert failure["consistency_ratio"] >= 0.10
    assert len(failure["worst_pairs"]) > 0


def test_compute_endpoint_rejects_wrong_cluster_names():
    payload = {
        "cluster_comparison": {
            "items": ["Topographic", "Hydrological", "Land Use", "Infrastructure", "NotACluster"],
            "matrix": _consistent_matrix([5.0, 3.0, 2.0, 1.0, 1.0]),
        },
        "within_cluster_comparisons": {},
    }

    response = client.post("/api/ahp/compute", json=payload)

    assert response.status_code == 422


def test_compute_endpoint_rejects_non_square_matrix():
    payload = {
        "cluster_comparison": {"items": ["A", "B", "C"], "matrix": [[1, 2], [0.5, 1]]},
        "within_cluster_comparisons": {},
    }

    response = client.post("/api/ahp/compute", json=payload)

    assert response.status_code == 422
