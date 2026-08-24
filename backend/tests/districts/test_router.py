"""Tests for the districts API (GET /api/districts, /{pcode}, /{pcode}/aoi)
end to end via FastAPI's TestClient, against the tiny synthetic fixture
(tests/districts/conftest.py points config.LOCAL_ADMIN_DISTRICTS_PATH at
it) — mirrors tests/basins/test_router.py's own structure.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.data import config
from app.data.districts import reset_districts_cache
from app.main import app

client = TestClient(app)

DISTRICT_A = "NP9901"
DISTRICT_MATCHING_TEST_AOI = "NP9903"


def test_list_districts_returns_a_geojson_feature_collection():
    response = client.get("/api/districts")

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    pcodes = {f["properties"]["pcode"] for f in body["features"]}
    assert DISTRICT_A in pcodes
    a = next(f for f in body["features"] if f["properties"]["pcode"] == DISTRICT_A)
    assert a["properties"]["name"] == "Testpur"
    assert a["properties"]["province"] == "TestProvince"
    assert a["type"] == "Feature"
    assert a["geometry"]["type"] == "Polygon"


def test_get_district_detail_returns_name_province_and_area():
    response = client.get(f"/api/districts/{DISTRICT_A}")

    assert response.status_code == 200
    body = response.json()
    assert body["pcode"] == DISTRICT_A
    assert body["name"] == "Testpur"
    assert body["province"] == "TestProvince"
    assert body["area_km2"] > 0


def test_get_district_detail_404s_for_unknown_pcode():
    response = client.get("/api/districts/NP0000")

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "district_not_found"


def test_get_district_aoi_returns_a_shape_directly_usable_by_overlay_compute():
    response = client.get(f"/api/districts/{DISTRICT_MATCHING_TEST_AOI}/aoi")

    assert response.status_code == 200
    body = response.json()
    assert len(body["bbox"]) == 4
    assert body["polygon"]["type"] == "Polygon"

    from app.common.aoi import AOIInput

    aoi_input = AOIInput(**body)
    domain_aoi = aoi_input.to_domain()
    assert domain_aoi.polygon is not None


def test_get_district_aoi_404s_for_unknown_pcode():
    response = client.get("/api/districts/NP0000/aoi")
    assert response.status_code == 404


def test_districts_endpoints_503_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_ADMIN_DISTRICTS_PATH", tmp_path / "missing.shp")
    reset_districts_cache()

    response = client.get("/api/districts")

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "districts_unavailable"
