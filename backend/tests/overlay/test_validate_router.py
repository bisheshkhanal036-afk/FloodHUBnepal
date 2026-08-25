"""Tests for GET /api/overlay/validation-events and POST
/api/overlay/validate. Mocks resolve_criterion_raster (same as
test_router.py's own POST /compute tests) and
app.data.validation_extent.get_observed_flood_mask, so these never touch
Phase 2's real data-fetch paths or a real shapefile.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.data.grid import AOIGrid
from app.main import app

client = TestClient(app)

GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=10, height=10)


def _payload(event="fake_event"):
    return {
        "aoi": {"bbox": [85.3050, 27.7020, 85.3110, 27.7080]},
        "criteria": [
            {"id": "a", "source": "dem_elevation", "reclassification_rules": [{"min": 0, "max": None, "risk_class": 1}]}
        ],
        "final_weights": {"a": 1.0},
        "complete": True,
        "event": event,
    }


def _mock_criterion_raster(monkeypatch, high_risk_top_rows=3):
    """A 10x10 raster: the top `high_risk_top_rows` rows are risk_class 5
    (highest), everything else risk_class 1 -- a clear, well-defined
    "high-risk zone" for the observed-flood mock below to line up with
    or diverge from.
    """
    reclassified = np.ones((10, 10), dtype=np.uint8)
    reclassified[:high_risk_top_rows, :] = 5

    def fake(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        return reclassified, GRID, "Fake Source Attribution", None

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake)


def _mock_observed_mask(monkeypatch, flooded_top_rows=3, event_key="fake_event", label="Fake Event"):
    observed = np.zeros((10, 10), dtype=np.uint8)
    observed[:flooded_top_rows, :] = 1

    class FakeMaskResult:
        pass

    FakeMaskResult.observed_flooded = observed
    FakeMaskResult.grid = GRID
    FakeMaskResult.attribution = "Fake Validation Attribution — CC BY-SA"
    FakeMaskResult.event = event_key
    FakeMaskResult.label = label

    def fake(aoi, event_arg):
        assert event_arg == event_key
        return FakeMaskResult()

    monkeypatch.setattr("app.overlay.validate.get_observed_flood_mask", fake)


def test_validate_endpoint_returns_a_high_auc_when_risk_and_observed_flooding_align(monkeypatch):
    _mock_criterion_raster(monkeypatch, high_risk_top_rows=3)
    _mock_observed_mask(monkeypatch, flooded_top_rows=3)

    response = client.post("/api/overlay/validate", json=_payload())

    assert response.status_code == 200
    body = response.json()
    # Perfect alignment (same 3 rows both "high risk" and "flooded") ->
    # AUC should be high, close to the closed-form 1 - p/2 for p=0.3.
    assert body["auc"] > 0.8
    assert body["pr_auc"] > 0.8
    assert body["n_valid_pixels"] == 100
    assert body["n_observed_flooded_pixels"] == 30
    assert body["observed_flooded_fraction"] == pytest.approx(0.3)
    assert body["event"] == "fake_event"
    assert body["event_label"] == "Fake Event"
    assert "Fake Source Attribution" in body["attribution"]
    assert "Fake Validation Attribution — CC BY-SA" in body["attribution"]
    assert len(body["risk_surface_cache_key"]) == 64
    assert body["curve"][0] == [0.0, 0.0]
    assert body["curve"][-1] == [1.0, 1.0]
    # risk_class 5 (top 3 rows) is High/Very-High hazard, identical to
    # the observed-flooded rows -> a perfect confusion matrix too.
    assert body["precision"] == pytest.approx(1.0)
    assert body["recall"] == pytest.approx(1.0)
    assert body["f1"] == pytest.approx(1.0)
    assert body["iou"] == pytest.approx(1.0)
    assert body["true_positive_pixels"] == 30
    assert body["false_positive_pixels"] == 0
    assert body["false_negative_pixels"] == 0
    assert body["true_negative_pixels"] == 70


def test_validate_endpoint_returns_a_low_auc_when_risk_and_observed_flooding_are_opposite(monkeypatch):
    """High-risk zone is the TOP 3 rows; observed flooding is the BOTTOM
    3 rows -- the model ranks exactly the wrong area as highest-risk.
    """
    _mock_criterion_raster(monkeypatch, high_risk_top_rows=3)
    observed = np.zeros((10, 10), dtype=np.uint8)
    observed[7:, :] = 1

    class FakeMaskResult:
        observed_flooded = observed
        grid = GRID
        attribution = "Fake Validation Attribution"
        event = "fake_event"
        label = "Fake Event"

    monkeypatch.setattr("app.overlay.validate.get_observed_flood_mask", lambda aoi, event: FakeMaskResult())

    response = client.post("/api/overlay/validate", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["auc"] < 0.3
    # High/Very-High hazard (top 3 rows) and observed flooding (bottom 3
    # rows) never overlap -> every threshold-based metric bottoms out.
    assert body["precision"] == 0.0
    assert body["recall"] == 0.0
    assert body["f1"] == 0.0
    assert body["iou"] == 0.0


def test_validate_endpoint_422s_when_aoi_does_not_overlap_the_event(monkeypatch):
    _mock_criterion_raster(monkeypatch)
    _mock_observed_mask(monkeypatch, flooded_top_rows=0)  # no observed flooding anywhere

    response = client.post("/api/overlay/validate", json=_payload())

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "overlay_validation_error"


def test_validate_endpoint_surfaces_missing_event_as_503(monkeypatch):
    _mock_criterion_raster(monkeypatch)
    from app.data.errors import DataSourceUnavailableError

    def fake(aoi, event):
        raise DataSourceUnavailableError("simulated: unrecognized event")

    monkeypatch.setattr("app.overlay.validate.get_observed_flood_mask", fake)

    response = client.post("/api/overlay/validate", json=_payload(event="not_a_real_event"))

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "data_source_unavailable"


def test_validate_endpoint_reuses_computes_own_cache(monkeypatch):
    """The same aoi/criteria/weights already computed via POST /compute
    must not re-resolve the criterion raster a second time when POST
    /validate is called right after -- confirmed by counting calls into
    the mocked resolve_criterion_raster.
    """
    calls = []
    reclassified = np.ones((10, 10), dtype=np.uint8)
    reclassified[:3, :] = 5

    def fake_resolve(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        calls.append(1)
        return reclassified, GRID, "Fake Source Attribution", None

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake_resolve)
    _mock_observed_mask(monkeypatch, flooded_top_rows=3)

    payload = _payload()
    compute_payload = {k: v for k, v in payload.items() if k != "event"}
    first = client.post("/api/overlay/compute", json=compute_payload)
    assert first.status_code == 200
    second = client.post("/api/overlay/validate", json=payload)
    assert second.status_code == 200

    assert len(calls) == 1
    assert second.json()["risk_surface_cache_key"] == first.json()["cache_key"]


def test_validation_events_endpoint_lists_registered_events(monkeypatch):
    from app.data import config

    monkeypatch.setattr(
        config,
        "VALIDATION_EVENTS",
        {"nepal_2024_terai": {"label": "Nepal floods, 27 Sep 2024", "path": "x.shp", "attribution": "x"}},
    )

    response = client.get("/api/overlay/validation-events")

    assert response.status_code == 200
    assert response.json() == [{"key": "nepal_2024_terai", "label": "Nepal floods, 27 Sep 2024"}]


# --- GET /api/overlay/validation-events/{event}/extent.geojson ---
# get_validation_extent_geojson is mocked here (its own real behavior,
# including the lru_cache, is covered by test_validation_extent.py) --
# these tests are about the route's own request/response wiring and
# status-code mapping.


def _router_module():
    # app/overlay/__init__.py does `from .router import router` -- the
    # APIRouter *instance* it re-exports as app.overlay.router shadows
    # the submodule of the exact same name, so a dotted-string
    # monkeypatch.setattr("app.overlay.router.name", ...) resolves to
    # the instance (and 404s with an AttributeError) rather than the
    # module. sys.modules is the same workaround test_router.py's own
    # compute_criterion_breaks/fetch_meteor_flood_tile patches already
    # use for this identical collision.
    import sys

    return sys.modules["app.overlay.router"]


def test_validation_extent_geojson_endpoint_returns_the_geojson(monkeypatch):
    fake_geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}, "properties": {}}]}
    monkeypatch.setattr(_router_module(), "get_validation_extent_geojson", lambda event: fake_geojson)

    response = client.get("/api/overlay/validation-events/nepal_2024_terai/extent.geojson")

    assert response.status_code == 200
    assert response.json() == fake_geojson


def test_validation_extent_geojson_endpoint_404s_for_an_unregistered_event(monkeypatch):
    from app.data import config
    from app.data.errors import DataSourceUnavailableError

    monkeypatch.setattr(config, "VALIDATION_EVENTS", {})

    def fake(event):
        raise DataSourceUnavailableError("simulated: unrecognized event")

    monkeypatch.setattr(_router_module(), "get_validation_extent_geojson", fake)

    response = client.get("/api/overlay/validation-events/not_a_real_event/extent.geojson")

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "validation_event_not_found"


def test_validation_extent_geojson_endpoint_503s_for_a_registered_event_with_a_missing_file(monkeypatch):
    from app.data import config
    from app.data.errors import DataSourceUnavailableError

    monkeypatch.setattr(
        config,
        "VALIDATION_EVENTS",
        {"nepal_2024_terai": {"label": "x", "path": "missing.shp", "attribution": "x"}},
    )

    def fake(event):
        raise DataSourceUnavailableError("simulated: no local file")

    monkeypatch.setattr(_router_module(), "get_validation_extent_geojson", fake)

    response = client.get("/api/overlay/validation-events/nepal_2024_terai/extent.geojson")

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "data_source_unavailable"
