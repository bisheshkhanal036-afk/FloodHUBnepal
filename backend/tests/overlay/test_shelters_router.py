"""Tests for POST /api/overlay/shelters end to end, via FastAPI's
TestClient -- same shape as test_report_router.py's own tests, with
resolve_criterion_raster/get_osm_features/get_population/
compute_distance_raster mocked so these don't touch Phase 2's real
data-fetch paths.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
from fastapi.testclient import TestClient
from shapely.geometry import box

from app.data.grid import AOIGrid
from app.data.osm import OSMResult
from app.data.population import PopulationResult
from app.main import app

client = TestClient(app)

GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=100.0, width=10, height=10)
_RASTER = np.zeros((10, 10), dtype=np.uint8)
_RASTER[:, 0:5] = 2  # safe half
_RASTER[:, 5:10] = 5  # high-hazard half


def _fake_dependencies(monkeypatch, buildings):
    def fake_resolve(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        return _RASTER.copy(), GRID, "Fake Source Attribution", None

    def fake_population(aoi):
        return PopulationResult(
            density=np.full((10, 10), 1000.0, dtype=np.float32), grid=GRID, nodata=-9999.0, source_used="fake"
        )

    def fake_osm(aoi):
        return OSMResult(buildings=buildings, roads=gpd.GeoDataFrame(geometry=[], crs="EPSG:32645"), source_used="fake")

    def fake_distance(features, grid):
        return np.full((grid.height, grid.width), 30.0, dtype=np.float32)

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake_resolve)
    monkeypatch.setattr("app.overlay.shelters.get_population", fake_population)
    monkeypatch.setattr("app.overlay.shelters.get_osm_features", fake_osm)
    monkeypatch.setattr("app.overlay.shelters.compute_distance_raster", fake_distance)


def _payload(**overrides):
    payload = {
        "aoi": {"bbox": [85.3050, 27.7020, 85.3110, 27.7080]},
        "criteria": [
            {"id": "a", "source": "dem_elevation", "reclassification_rules": [{"min": 0, "max": None, "risk_class": 1}]},
        ],
        "final_weights": {"a": 1.0},
        "complete": True,
    }
    payload.update(overrides)
    return payload


def _buildings_gdf(*geoms):
    return gpd.GeoDataFrame({"id": range(len(geoms))}, geometry=list(geoms), crs="EPSG:32645")


def test_shelters_endpoint_ranks_safe_candidates_and_excludes_unsafe_ones(monkeypatch):
    safe = box(10, 40, 30, 60)  # 400 m^2, safe half -> included
    unsafe = box(60, 40, 90, 60)  # 600 m^2, high-hazard half -> excluded
    _fake_dependencies(monkeypatch, _buildings_gdf(safe, unsafe))

    response = client.post("/api/overlay/shelters", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert len(body["cache_key"]) == 64
    assert body["risk_surface_data_url"] == f"/api/overlay/risk_surface/{body['cache_key']}.tif"
    assert body["total_buildings_in_aoi"] == 2
    assert body["excluded_high_hazard"] == 1
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["hazard_class"] == 2
    assert body["candidates"][0]["rank"] == 1
    assert body["candidates"][0]["geometry"]["type"] == "Polygon"


def test_shelters_endpoint_respects_min_footprint_area_and_top_n(monkeypatch):
    small = box(10, 10, 15, 15)  # 25 m^2
    large_a = box(10, 40, 30, 60)  # 400 m^2
    large_b = box(10, 70, 30, 90)  # 400 m^2
    _fake_dependencies(monkeypatch, _buildings_gdf(small, large_a, large_b))

    response = client.post("/api/overlay/shelters", json=_payload(min_footprint_area_m2=100.0, top_n=1))

    assert response.status_code == 200
    body = response.json()
    assert body["excluded_too_small"] == 1
    assert len(body["candidates"]) == 1


def test_shelters_endpoint_rejects_incomplete_weights(monkeypatch):
    _fake_dependencies(monkeypatch, _buildings_gdf())

    response = client.post("/api/overlay/shelters", json=_payload(complete=False))

    assert response.status_code == 422
