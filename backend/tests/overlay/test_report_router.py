"""Tests for POST /api/overlay/report and GET /api/overlay/hazard_classes/
{cache_key}.tif end to end, via FastAPI's TestClient. resolve_criterion_
raster/get_osm_features/get_population are mocked so these tests don't
touch Phase 2's real data-fetch paths -- same shape as test_router.py's
own POST /compute tests.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
from fastapi.testclient import TestClient
from shapely.geometry import Point

from app.data.grid import AOIGrid
from app.data.osm import OSMResult
from app.data.population import PopulationResult
from app.main import app

client = TestClient(app)

GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=2, height=2)


def _fake_dependencies(monkeypatch, class_value=3, density_value=50000.0, buildings=None):
    def fake_resolve(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        return np.full((2, 2), class_value, dtype=np.uint8), GRID, "Fake Source Attribution", None

    def fake_population(aoi):
        return PopulationResult(
            density=np.full((2, 2), density_value, dtype=np.float32), grid=GRID, nodata=-9999.0, source_used="fake"
        )

    def fake_osm(aoi):
        gdf = buildings if buildings is not None else gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645")
        return OSMResult(buildings=gdf, roads=gpd.GeoDataFrame(geometry=[]), source_used="fake")

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake_resolve)
    monkeypatch.setattr("app.overlay.report.get_population", fake_population)
    monkeypatch.setattr("app.overlay.report.get_osm_features", fake_osm)


def _report_payload(method="equal", **overrides):
    payload = {
        "aoi": {"bbox": [85.3050, 27.7020, 85.3110, 27.7080]},
        "criteria": [
            {"id": "a", "source": "dem_elevation", "name": "Elevation",
             "reclassification_rules": [{"min": 0, "max": None, "risk_class": 1}]},
        ],
        "final_weights": {"a": 1.0},
        "complete": True,
        "weighting": {"method": method},
    }
    payload.update(overrides)
    return payload


def test_report_endpoint_returns_a_complete_report(monkeypatch):
    _fake_dependencies(monkeypatch)

    response = client.post("/api/overlay/report", json=_report_payload())

    assert response.status_code == 200
    body = response.json()
    assert len(body["cache_key"]) == 64
    assert body["risk_surface_data_url"] == f"/api/overlay/risk_surface/{body['cache_key']}.tif"
    assert body["hazard_classes_data_url"] == f"/api/overlay/hazard_classes/{body['cache_key']}.tif"
    assert len(body["zonal_stats"]) == 5
    assert body["criteria"][0]["name"] == "Elevation"
    assert body["weighting"]["method"] == "equal"
    assert body["weighting"]["ahp_cluster_comparison"] is None
    assert body["buildings"]["type"] == "FeatureCollection"


def test_report_endpoint_ahp_mode_returns_the_cluster_breakdown(monkeypatch):
    _fake_dependencies(monkeypatch)
    all_ones_5 = [[1.0] * 5 for _ in range(5)]
    payload = _report_payload(
        method="ahp",
        weighting={
            "method": "ahp",
            "cluster_comparison": {
                "items": ["Topographic", "Hydrological", "Land Use", "Infrastructure", "Exposure"],
                "matrix": all_ones_5,
            },
            "within_cluster_comparisons": {"Topographic": {"items": ["a"], "matrix": [[1.0]]}},
        },
    )

    response = client.post("/api/overlay/report", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["weighting"]["ahp_cluster_comparison"]["consistent"] is True
    assert body["criteria"][0]["cluster"] == "Topographic"


def test_report_endpoint_ahp_mode_without_matrices_is_422(monkeypatch):
    _fake_dependencies(monkeypatch)
    payload = _report_payload(method="ahp", weighting={"method": "ahp"})

    response = client.post("/api/overlay/report", json=payload)

    assert response.status_code == 422


def test_report_endpoint_buildings_are_tagged_with_hazard_class(monkeypatch):
    # GRID here is a mock grid at origin (0,0) in EPSG:32645, unrelated to
    # the real AOI's real-world UTM location -- the building geometry is
    # given directly in EPSG:32645, inside the mock grid's own tiny
    # extent (x:[0,20), y:(-20,0]), rather than a real EPSG:4326 point
    # (which would reproject far outside this fake grid and correctly
    # come back unclassified -- that path is covered by
    # test_building_classification.py's own dedicated "outside the grid"
    # test, not the concern of this HTTP-layer test).
    buildings = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(5, -5).buffer(1)], crs="EPSG:32645")
    _fake_dependencies(monkeypatch, class_value=4, buildings=buildings)

    response = client.post("/api/overlay/report", json=_report_payload())

    assert response.status_code == 200
    body = response.json()
    assert len(body["buildings"]["features"]) == 1
    feature = body["buildings"]["features"][0]
    assert feature["type"] == "Feature"
    assert feature["properties"]["hazard_class"] == 4
    assert feature["properties"]["hazard_label"] == "High"


def test_report_endpoint_rejects_aoi_exceeding_area_cap(monkeypatch):
    _fake_dependencies(monkeypatch)
    payload = _report_payload()
    payload["aoi"] = {"bbox": [85.0, 27.0, 85.5, 27.5]}  # ~2,500+ km^2

    response = client.post("/api/overlay/report", json=payload)

    assert response.status_code == 422


# --- GET /api/overlay/hazard_classes/{cache_key}.tif ---


def test_hazard_classes_file_route_serves_the_geotiff_after_a_successful_compute(monkeypatch):
    _fake_dependencies(monkeypatch)
    compute_response = client.post(
        "/api/overlay/compute",
        json={
            "aoi": {"bbox": [85.3050, 27.7020, 85.3110, 27.7080]},
            "criteria": [{"id": "a", "source": "dem_elevation", "reclassification_rules": [{"min": 0, "max": None, "risk_class": 1}]}],
            "final_weights": {"a": 1.0},
            "complete": True,
        },
    )
    hazard_url = compute_response.json()["hazard_classes_data_url"]

    file_response = client.get(hazard_url)

    assert file_response.status_code == 200
    assert file_response.headers["content-type"] == "image/tiff"
    assert file_response.content[:2] in (b"II", b"MM")


def test_hazard_classes_file_route_404s_for_a_cache_key_that_was_never_computed():
    response = client.get("/api/overlay/hazard_classes/" + "a" * 64 + ".tif")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "risk_surface_not_found"


def test_hazard_classes_file_route_422s_for_a_malformed_cache_key():
    response = client.get("/api/overlay/hazard_classes/not-a-valid-hash.tif")
    assert response.status_code == 422


# --- per-criterion raster snapshots: only available after POST /report ---


def test_criterion_raster_404s_after_a_plain_compute_before_any_report(monkeypatch):
    """The core of the "only after the report" requirement, verified at
    the HTTP boundary: a cache_key with a fully computed risk surface
    (and even its hazard_classes derived) still 404s for a criterion
    raster until POST /report has actually been called for it.
    """
    _fake_dependencies(monkeypatch)
    compute_response = client.post(
        "/api/overlay/compute",
        json={
            "aoi": {"bbox": [85.3050, 27.7020, 85.3110, 27.7080]},
            "criteria": [{"id": "a", "source": "dem_elevation", "reclassification_rules": [{"min": 0, "max": None, "risk_class": 1}]}],
            "final_weights": {"a": 1.0},
            "complete": True,
        },
    )
    cache_key = compute_response.json()["cache_key"]

    response = client.get(f"/api/overlay/criterion_raster/{cache_key}/a.tif")

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "criterion_raster_not_found"


def test_criterion_raster_file_route_serves_the_geotiff_after_a_report(monkeypatch):
    _fake_dependencies(monkeypatch)

    report_response = client.post("/api/overlay/report", json=_report_payload())
    body = report_response.json()
    data_url = body["criteria"][0]["data_url"]
    assert data_url == f"/api/overlay/criterion_raster/{body['cache_key']}/a.tif"

    file_response = client.get(data_url)

    assert file_response.status_code == 200
    assert file_response.headers["content-type"] == "image/tiff"
    assert file_response.content[:2] in (b"II", b"MM")


def test_criterion_raster_file_route_422s_for_a_malformed_criterion_id():
    response = client.get("/api/overlay/criterion_raster/" + "a" * 64 + "/../../etc.tif")
    assert response.status_code in (404, 422)  # routing itself rejects a path-shaped segment; never a 200

    response = client.get("/api/overlay/criterion_raster/" + "a" * 64 + "/not valid!.tif")
    assert response.status_code == 422
