"""Tests for the basins API (GET /api/basins, /{hybas_id}, /{hybas_id}/aoi)
end to end via FastAPI's TestClient, against the tiny synthetic fixture
(tests/basins/conftest.py points config.LOCAL_BASINS_PATH at it)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.data import config
from app.data.basins import reset_basins_cache
from app.main import app

client = TestClient(app)

BASIN_FULLY_IN_NEPAL = 4080000010
BASIN_PARTIAL = 4080000020
BASIN_SMALL = 4080000040  # tiny (~0.4 km^2), fits under the overlay endpoint's area cap


def test_list_basins_returns_a_geojson_feature_collection_with_support_status():
    response = client.get("/api/basins")

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    ids = {f["properties"]["hybas_id"] for f in body["features"]}
    assert BASIN_FULLY_IN_NEPAL in ids
    fully_in = next(f for f in body["features"] if f["properties"]["hybas_id"] == BASIN_FULLY_IN_NEPAL)
    assert fully_in["properties"]["support_status"] == "fully_in_nepal"
    assert fully_in["type"] == "Feature"
    assert fully_in["geometry"]["type"] == "Polygon"


def test_get_basin_detail_returns_area_and_status():
    response = client.get(f"/api/basins/{BASIN_PARTIAL}")

    assert response.status_code == 200
    body = response.json()
    assert body["hybas_id"] == BASIN_PARTIAL
    assert body["support_status"] == "partial_likely_adequate"
    assert 50.0 <= body["pct_in_nepal"] < 98.0
    assert body["area_km2"] > 0


def test_get_basin_detail_404s_for_unknown_id():
    response = client.get("/api/basins/999999999")

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "basin_not_found"


def test_get_basin_aoi_returns_a_shape_directly_usable_by_overlay_compute():
    # BASIN_SMALL, not BASIN_FULLY_IN_NEPAL: the latter is a realistically
    # large (~11,000 km^2) basin -- accepted regardless of size since a
    # polygon AOI is exempt from the overlay endpoint's area cap entirely
    # (app/common/aoi.py), but a small fixture keeps this test's own
    # focus (the response shape round-tripping into AOIInput) fast and
    # unrelated to the cap exemption itself, which is covered by
    # tests/common/test_aoi.py's own dedicated tests.
    response = client.get(f"/api/basins/{BASIN_SMALL}/aoi")

    assert response.status_code == 200
    body = response.json()
    assert len(body["bbox"]) == 4
    assert body["polygon"]["type"] == "Polygon"

    # This response shape must be droppable straight into
    # OverlayComputeRequest.aoi (app.common.aoi.AOIInput) unchanged.
    from app.common.aoi import AOIInput

    aoi_input = AOIInput(**body)
    domain_aoi = aoi_input.to_domain()
    assert domain_aoi.polygon is not None


def test_get_basin_aoi_404s_for_unknown_id():
    response = client.get("/api/basins/999999999/aoi")
    assert response.status_code == 404


def test_basins_endpoints_503_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_BASINS_PATH", tmp_path / "missing.shp")
    reset_basins_cache()

    response = client.get("/api/basins")

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "basins_unavailable"
