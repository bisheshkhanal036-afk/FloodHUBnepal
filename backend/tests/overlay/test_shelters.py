from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import box

from app.data.grid import AOIGrid
from app.data.osm import OSMResult
from app.data.population import PopulationResult
from app.overlay.hazard_classes import HIGH_RISK_CLASSES
from app.overlay.service import OverlayCriterionRequest
from app.overlay.shelters import _min_max_normalize, identify_shelter_sites

# 10x10 grid, 10m pixels, x:[0,100), y:[0,100), origin_y=100 (north-up:
# y decreases with row) -- same construction test_building_classification.py
# already uses, so the hand-computed pixel/coordinate math below isn't
# distorted by a real reprojection.
GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=100.0, width=10, height=10)

# Reclassified single-criterion raster: class 2 (safe) for x < 50, class 5
# (high hazard) for x >= 50 -- with weight=1.0 on this one criterion, the
# combined risk surface reproduces this exactly, so hazard classes land
# where expected without needing to hand-derive the weighted-sum formula.
_RASTER = np.zeros((10, 10), dtype=np.uint8)
_RASTER[:, 0:5] = 2
_RASTER[:, 5:10] = 5


def _fake_resolve(monkeypatch):
    def fake(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        return _RASTER.copy(), GRID, "Fake Source Attribution", None

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake)


def _fake_osm_features(monkeypatch, buildings, roads=None):
    def fake(aoi):
        return OSMResult(
            buildings=buildings,
            roads=roads if roads is not None else gpd.GeoDataFrame(geometry=[], crs="EPSG:32645"),
            source_used="fake",
        )

    monkeypatch.setattr("app.overlay.shelters.get_osm_features", fake)


def _fake_population(monkeypatch, density_value=10000.0):
    def fake(aoi):
        density = np.full((10, 10), density_value, dtype=np.float32)
        return PopulationResult(density=density, grid=GRID, nodata=-9999.0, source_used="fake")

    monkeypatch.setattr("app.overlay.shelters.get_population", fake)


def _fake_distance(monkeypatch, value=25.0):
    def fake(features, grid):
        return np.full((grid.height, grid.width), value, dtype=np.float32)

    monkeypatch.setattr("app.overlay.shelters.compute_distance_raster", fake)


def _building(x0, y0, x1, y1, id_=1):
    return gpd.GeoDataFrame({"id": [id_]}, geometry=[box(x0, y0, x1, y1)], crs="EPSG:32645")


def _buildings(*geoms):
    return gpd.GeoDataFrame({"id": range(len(geoms))}, geometry=list(geoms), crs="EPSG:32645")


CRITERIA = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]


def test_excludes_too_small_and_high_hazard_buildings(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    _fake_distance(monkeypatch)
    _fake_population(monkeypatch)

    safe_large = box(10, 40, 30, 60)  # 20x20=400 m^2, x<50 -> hazard class 2, above the 250 m^2 default
    safe_small = box(10, 10, 15, 15)  # 5x5=25 m^2, x<50 -> too small, excluded regardless of hazard
    unsafe_large = box(60, 40, 90, 60)  # 30x20=600 m^2, x>=50 -> hazard class 5, excluded outright

    _fake_osm_features(monkeypatch, _buildings(safe_large, safe_small, unsafe_large))

    result = identify_shelter_sites(test_aoi, CRITERIA, {"a": 1.0}, complete=True)

    assert result.total_buildings_in_aoi == 3
    assert result.excluded_too_small == 1
    assert result.excluded_high_hazard == 1
    assert result.excluded_no_data == 0
    assert len(result.candidates) == 1
    assert result.candidates[0].hazard_class == 2
    assert result.candidates[0].hazard_class not in HIGH_RISK_CLASSES
    assert result.candidates[0].rank == 1
    assert len(result.cache_key) == 64


def test_ranking_prefers_closer_road_and_higher_population(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    _fake_population(monkeypatch, density_value=500.0)

    # Two equally-safe, equally-sized candidates (both hazard class 2) --
    # only accessibility should decide the ranking when service_weight=0.
    near_road = box(0, 0, 20, 20)
    far_road = box(20, 20, 40, 40)
    _fake_osm_features(monkeypatch, _buildings(near_road, far_road))

    def fake_distance(features, grid):
        arr = np.full((grid.height, grid.width), 500.0, dtype=np.float32)
        arr[8:10, 0:2] = 5.0  # near_road's footprint (rows 8-9, cols 0-1) sits close to a road
        return arr

    monkeypatch.setattr("app.overlay.shelters.compute_distance_raster", fake_distance)

    result = identify_shelter_sites(
        test_aoi, CRITERIA, {"a": 1.0}, complete=True, safety_weight=0.0, accessibility_weight=1.0, service_weight=0.0
    )

    assert len(result.candidates) == 2
    assert result.candidates[0].rank == 1
    assert result.candidates[0].distance_to_road_m < result.candidates[1].distance_to_road_m


def test_zero_roads_in_aoi_yields_none_distance_not_excluded(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    _fake_population(monkeypatch)

    def fake_distance_no_roads(features, grid):
        return np.full((grid.height, grid.width), -1.0, dtype=np.float32)  # DISTANCE_RASTER_NODATA

    monkeypatch.setattr("app.overlay.shelters.compute_distance_raster", fake_distance_no_roads)
    _fake_osm_features(monkeypatch, _buildings(box(10, 40, 30, 60)))

    result = identify_shelter_sites(test_aoi, CRITERIA, {"a": 1.0}, complete=True)

    assert len(result.candidates) == 1
    assert result.candidates[0].distance_to_road_m is None
    # A missing accessibility signal shouldn't crash scoring or force a
    # zero score -- see _min_max_normalize's own None-handling.
    assert 0.0 <= result.candidates[0].suitability_score <= 1.0


def test_no_buildings_in_aoi_returns_empty_result(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    _fake_distance(monkeypatch)
    _fake_population(monkeypatch)
    _fake_osm_features(monkeypatch, gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645"))

    result = identify_shelter_sites(test_aoi, CRITERIA, {"a": 1.0}, complete=True)

    assert result.candidates == []
    assert result.total_buildings_in_aoi == 0


def test_top_n_limits_returned_candidates(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    _fake_distance(monkeypatch)
    _fake_population(monkeypatch)

    # 4 disjoint, equally safe, equally sized candidate buildings.
    geoms = [box(x, 10, x + 20, 30) for x in (0, 25, 60, 85)]
    _fake_osm_features(monkeypatch, _buildings(*geoms))

    result = identify_shelter_sites(test_aoi, CRITERIA, {"a": 1.0}, complete=True, top_n=2)

    assert len(result.candidates) == 2
    assert [c.rank for c in result.candidates] == [1, 2]


# --- _min_max_normalize unit tests ---


def test_min_max_normalize_higher_is_better():
    scores = _min_max_normalize([0.0, 5.0, 10.0], higher_is_better=True)
    assert scores == [0.0, 0.5, 1.0]


def test_min_max_normalize_lower_is_better():
    scores = _min_max_normalize([0.0, 5.0, 10.0], higher_is_better=False)
    assert scores == [1.0, 0.5, 0.0]


def test_min_max_normalize_none_scores_at_midpoint():
    scores = _min_max_normalize([0.0, None, 10.0], higher_is_better=True)
    assert scores == [0.0, 0.5, 1.0]


def test_min_max_normalize_all_equal_scores_at_midpoint():
    scores = _min_max_normalize([5.0, 5.0, 5.0], higher_is_better=True)
    assert scores == [0.5, 0.5, 0.5]


def test_min_max_normalize_all_none():
    assert _min_max_normalize([None, None], higher_is_better=True) == [0.5, 0.5]
