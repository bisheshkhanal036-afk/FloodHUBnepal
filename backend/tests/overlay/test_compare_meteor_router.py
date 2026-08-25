"""Tests for POST /api/overlay/compare-meteor: agreement between a
computed risk surface and METEOR's own modeled flood hazard -- NOT
validation against real-world accuracy (that's test_validate_router.py's
own job). Mocks resolve_criterion_raster (same as test_router.py's/
test_validate_router.py's own POST /compute tests) and
app.data.meteor_flood.get_meteor_flood_hazard, so these never touch
Phase 2's real data-fetch paths or a real METEOR GeoTIFF.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.data.grid import AOIGrid
from app.main import app

client = TestClient(app)

GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=10, height=10)


def _payload():
    return {
        "aoi": {"bbox": [85.3050, 27.7020, 85.3110, 27.7080]},
        "criteria": [
            {"id": "a", "source": "dem_elevation", "reclassification_rules": [{"min": 0, "max": None, "risk_class": 1}]}
        ],
        "final_weights": {"a": 1.0},
        "complete": True,
    }


def _mock_criterion_raster(monkeypatch, high_risk_top_rows=3):
    """Same 10x10 raster as test_validate_router.py's own helper: the
    top `high_risk_top_rows` rows are risk_class 5, everything else 1.
    """
    reclassified = np.ones((10, 10), dtype=np.uint8)
    reclassified[:high_risk_top_rows, :] = 5

    def fake(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        return reclassified, GRID, "Fake Source Attribution", None

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake)


def _mock_meteor(monkeypatch, flooded_top_rows=3, depth=1.5):
    """A 10x10 METEOR depth grid: the top `flooded_top_rows` rows have a
    real modeled depth (> 0), everything else is exactly 0.0 (no
    modeled hazard) -- the same depth_m > 0 predicate
    meteor_comparison.py itself uses to binarize this.
    """
    depth_m = np.zeros((10, 10), dtype=np.float32)
    depth_m[:flooded_top_rows, :] = depth

    class FakeMeteorResult:
        pass

    FakeMeteorResult.depth_m = depth_m
    FakeMeteorResult.grid = GRID
    FakeMeteorResult.nodata = -9999.0
    FakeMeteorResult.source_used = "local:FD_1in100.tif"
    FakeMeteorResult.warning = None
    FakeMeteorResult.attribution = "Fake METEOR Attribution"

    def fake(aoi):
        return FakeMeteorResult()

    monkeypatch.setattr("app.overlay.meteor_comparison.get_meteor_flood_hazard", fake)


def test_compare_meteor_endpoint_returns_a_high_auc_when_risk_and_meteor_align(monkeypatch):
    _mock_criterion_raster(monkeypatch, high_risk_top_rows=3)
    _mock_meteor(monkeypatch, flooded_top_rows=3)

    response = client.post("/api/overlay/compare-meteor", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["auc"] > 0.8
    assert body["pr_auc"] > 0.8
    assert body["n_valid_pixels"] == 100
    assert body["n_meteor_flooded_pixels"] == 30
    assert body["meteor_flooded_fraction"] == pytest.approx(0.3)
    assert "Fake Source Attribution" in body["attribution"]
    assert "Fake METEOR Attribution" in body["attribution"]
    assert len(body["risk_surface_cache_key"]) == 64
    assert body["meteor_flood_type"]
    assert body["meteor_return_period"]
    # risk_class 5 (top 3 rows) is High/Very-High hazard, identical to
    # the METEOR-modeled-flooded rows -> a perfect confusion matrix.
    assert body["precision"] == pytest.approx(1.0)
    assert body["recall"] == pytest.approx(1.0)
    assert body["f1"] == pytest.approx(1.0)
    assert body["iou"] == pytest.approx(1.0)
    assert body["true_positive_pixels"] == 30
    assert body["false_positive_pixels"] == 0
    assert body["false_negative_pixels"] == 0
    assert body["true_negative_pixels"] == 70
    # Never validation language anywhere in the response.
    assert "event" not in body
    assert "event_label" not in body


def test_compare_meteor_endpoint_returns_a_low_auc_when_risk_and_meteor_disagree(monkeypatch):
    """High-risk zone is the TOP 3 rows; METEOR models the BOTTOM 3 rows
    as flooded -- the exact opposite region.
    """
    _mock_criterion_raster(monkeypatch, high_risk_top_rows=3)
    opposite_depth = np.zeros((10, 10), dtype=np.float32)
    opposite_depth[7:, :] = 2.0

    class FakeMeteorResult:
        depth_m = opposite_depth
        grid = GRID
        nodata = -9999.0
        source_used = "local:FD_1in100.tif"
        warning = None
        attribution = "Fake METEOR Attribution"

    monkeypatch.setattr("app.overlay.meteor_comparison.get_meteor_flood_hazard", lambda aoi: FakeMeteorResult())

    response = client.post("/api/overlay/compare-meteor", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["auc"] < 0.3
    assert body["precision"] == 0.0
    assert body["recall"] == 0.0
    assert body["f1"] == 0.0
    assert body["iou"] == 0.0


def test_compare_meteor_endpoint_422s_when_aoi_is_entirely_outside_meteors_domain(monkeypatch):
    _mock_criterion_raster(monkeypatch)
    _mock_meteor(monkeypatch, flooded_top_rows=0)  # depth_m is 0.0 everywhere -> no METEOR-modeled flooding at all

    response = client.post("/api/overlay/compare-meteor", json=_payload())

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["error"] == "overlay_validation_error"
    assert "METEOR" in body["detail"]["message"]


def test_compare_meteor_endpoint_surfaces_missing_local_meteor_file_as_503(monkeypatch):
    _mock_criterion_raster(monkeypatch)
    from app.data.errors import DataSourceUnavailableError

    def fake(aoi):
        raise DataSourceUnavailableError("simulated: no local METEOR file")

    monkeypatch.setattr("app.overlay.meteor_comparison.get_meteor_flood_hazard", fake)

    response = client.post("/api/overlay/compare-meteor", json=_payload())

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "data_source_unavailable"


def test_compare_meteor_endpoint_reuses_computes_own_cache(monkeypatch):
    """Same cache-sharing contract test_validate_router.py's own
    equivalent test checks for POST /validate: an AOI/criteria/weights
    combination already computed via POST /compute must not re-resolve
    the criterion raster a second time when POST /compare-meteor is
    called right after.
    """
    calls = []
    reclassified = np.ones((10, 10), dtype=np.uint8)
    reclassified[:3, :] = 5

    def fake_resolve(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        calls.append(1)
        return reclassified, GRID, "Fake Source Attribution", None

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake_resolve)
    _mock_meteor(monkeypatch, flooded_top_rows=3)

    first = client.post("/api/overlay/compute", json=_payload())
    assert first.status_code == 200
    second = client.post("/api/overlay/compare-meteor", json=_payload())
    assert second.status_code == 200

    assert len(calls) == 1
    assert second.json()["risk_surface_cache_key"] == first.json()["cache_key"]
