"""Unit tests for the generic Euclidean distance-to-nearest-feature
raster, plus the dist_to_river/dist_to_road cached wrappers built on it.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point

from app.data import config
from app.data.aoi import AOI
from app.data.attribution import OSM_ATTRIBUTION
from app.data.distance_raster import (
    DISTANCE_RASTER_NODATA,
    compute_distance_raster,
    get_distance_to_river,
    get_distance_to_road,
)
from app.data.grid import AOIGrid
from app.data.osm import OSMResult, WaterwaysResult

TEST_AOI_BBOX_4326 = (85.3050, 27.7020, 85.3110, 27.7080)


@pytest.fixture
def test_aoi() -> AOI:
    return AOI(bbox_4326=TEST_AOI_BBOX_4326)


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROCESSED_CACHE_DIR", tmp_path / "cache" / "processed")


def _small_grid() -> AOIGrid:
    return AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=50.0, width=5, height=5)


# --- compute_distance_raster: hand-calculable distances ---


def test_distance_from_a_straight_line_matches_hand_calculated_distances():
    grid = _small_grid()
    # A vertical line through the center of column index 2 (pixel
    # centers sit at x = 5, 15, 25, 35, 45 for columns 0-4).
    line = LineString([(25.0, 50.0), (25.0, 0.0)])
    features = gpd.GeoDataFrame({"id": [1]}, geometry=[line], crs="EPSG:32645")

    distance_m = compute_distance_raster(features, grid)

    expected_row = np.array([20.0, 10.0, 0.0, 10.0, 20.0], dtype=np.float32)
    for row in range(5):
        assert distance_m[row] == pytest.approx(expected_row, abs=1e-6)


def test_distance_from_a_point_matches_hand_calculated_radial_distances():
    grid = _small_grid()
    point = Point(25.0, 25.0)  # exactly the center of pixel (2, 2)
    features = gpd.GeoDataFrame({"id": [1]}, geometry=[point], crs="EPSG:32645")

    distance_m = compute_distance_raster(features, grid)

    assert distance_m[2, 2] == pytest.approx(0.0, abs=1e-6)
    assert distance_m[2, 1] == pytest.approx(10.0, abs=1e-6)
    assert distance_m[1, 1] == pytest.approx(10.0 * np.sqrt(2), abs=1e-6)


def test_reprojects_features_to_the_grid_crs_before_measuring(test_aoi):
    from app.data.grid import compute_aoi_grid

    grid = compute_aoi_grid(test_aoi.bounds_utm)
    # A point at the AOI's own center, given in EPSG:4326 -- must be
    # reprojected to the grid's EPSG:32645 before the distance transform,
    # or the resulting "distance in meters" would actually be nonsense
    # computed against raw degree coordinates (SPEC.md, CRS convention).
    center_lon = (TEST_AOI_BBOX_4326[0] + TEST_AOI_BBOX_4326[2]) / 2
    center_lat = (TEST_AOI_BBOX_4326[1] + TEST_AOI_BBOX_4326[3]) / 2
    features = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(center_lon, center_lat)], crs="EPSG:4326")

    distance_m = compute_distance_raster(features, grid)

    # The nearest pixel to the AOI's own center must be very close (well
    # under the AOI's own diagonal), not thousands of km away as it would
    # be if degrees were compared directly against meters.
    assert distance_m.min() < grid.resolution_m * 2


def test_empty_features_returns_all_nodata():
    grid = _small_grid()
    features = gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645")

    distance_m = compute_distance_raster(features, grid)

    assert (distance_m == DISTANCE_RASTER_NODATA).all()


# --- get_distance_to_river / get_distance_to_road: cached wrappers ---


def test_get_distance_to_river_uses_get_waterways(test_aoi, monkeypatch):
    calls = []

    def fake_get_waterways(aoi):
        calls.append(aoi)
        line = LineString([(85.306, 27.703), (85.306, 27.707)])
        return WaterwaysResult(
            waterways=gpd.GeoDataFrame({"id": [1]}, geometry=[line], crs="EPSG:4326"), source_used="fake"
        )

    monkeypatch.setattr("app.data.distance_raster.get_waterways", fake_get_waterways)

    result = get_distance_to_river(test_aoi)

    assert len(calls) == 1
    assert result.attribution == OSM_ATTRIBUTION
    assert result.nodata == DISTANCE_RASTER_NODATA
    assert result.distance_m.shape == (result.grid.height, result.grid.width)
    assert result.distance_m.min() >= 0.0


def test_get_distance_to_road_reuses_get_osm_features_roads_no_new_query(test_aoi, monkeypatch):
    """Per the brief: dist_to_road must reuse get_osm_features(aoi).roads
    -- no separate OSM query of its own.
    """
    calls = []

    def fake_get_osm_features(aoi):
        calls.append(aoi)
        line = LineString([(85.306, 27.703), (85.308, 27.707)])
        return OSMResult(
            buildings=gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326"),
            roads=gpd.GeoDataFrame({"id": [1]}, geometry=[line], crs="EPSG:4326"),
            source_used="fake",
        )

    monkeypatch.setattr("app.data.distance_raster.get_osm_features", fake_get_osm_features)

    result = get_distance_to_road(test_aoi)

    assert len(calls) == 1
    assert result.attribution == OSM_ATTRIBUTION
    assert result.distance_m.shape == (result.grid.height, result.grid.width)


def test_repeated_call_hits_the_processed_cache(test_aoi, monkeypatch):
    calls = []

    def fake_get_waterways(aoi):
        calls.append(aoi)
        return WaterwaysResult(waterways=gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326"), source_used="fake")

    monkeypatch.setattr("app.data.distance_raster.get_waterways", fake_get_waterways)

    first = get_distance_to_river(test_aoi)
    second = get_distance_to_river(test_aoi)

    assert len(calls) == 1
    assert np.array_equal(first.distance_m, second.distance_m)
