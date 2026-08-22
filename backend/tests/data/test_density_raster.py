"""Unit tests for the generic local coverage-density raster, plus the
building_density cached wrapper built on it.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from app.data import config
from app.data.aoi import AOI
from app.data.attribution import OSM_ATTRIBUTION
from app.data.density_raster import compute_density_raster, get_building_density
from app.data.grid import AOIGrid
from app.data.osm import OSMResult

TEST_AOI_BBOX_4326 = (85.3050, 27.7020, 85.3110, 27.7080)


@pytest.fixture
def test_aoi() -> AOI:
    return AOI(bbox_4326=TEST_AOI_BBOX_4326)


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROCESSED_CACHE_DIR", tmp_path / "cache" / "processed")


def _small_grid() -> AOIGrid:
    return AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=50.0, width=5, height=5)


# --- compute_density_raster: hand-calculable coverage fractions ---


def test_single_building_gives_hand_verified_coverage_fractions():
    grid = _small_grid()
    # A building exactly covering pixel (row=2, col=2): x in [20,30], y in [20,30].
    building = box(20, 20, 30, 30)
    features = gpd.GeoDataFrame({"id": [1]}, geometry=[building], crs="EPSG:32645")

    density = compute_density_raster(features, grid, window_radius_m=10.0)

    # Hand-verified: radius_px=1 gives a 5-cell "plus" kernel (corners
    # excluded, sqrt(2) > 1). Exactly one grid cell is covered, so every
    # pixel whose plus-shaped window includes (2,2) -- itself plus its 4
    # orthogonal neighbors -- gets 1/5 = 0.2 coverage; everywhere else 0.
    expected = np.zeros((5, 5), dtype=np.float32)
    expected[2, 2] = expected[1, 2] = expected[3, 2] = expected[2, 1] = expected[2, 3] = 0.2
    assert density == pytest.approx(expected, abs=1e-6)


def test_density_is_additive_across_multiple_buildings_in_the_same_window():
    grid = _small_grid()
    # Two adjacent buildings both covering cells inside the same plus-window around (2,2).
    b1 = box(20, 20, 30, 30)  # pixel (2,2)
    b2 = box(20, 10, 30, 20)  # pixel (3,2), directly below -- also in (2,2)'s plus-window
    features = gpd.GeoDataFrame({"id": [1, 2]}, geometry=[b1, b2], crs="EPSG:32645")

    density = compute_density_raster(features, grid, window_radius_m=10.0)

    # (2,2)'s own window (itself + 4 neighbors) now contains 2 covered cells -> 2/5 = 0.4.
    assert density[2, 2] == pytest.approx(0.4, abs=1e-6)


def test_empty_features_gives_all_zero_density_not_an_error():
    grid = _small_grid()
    features = gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645")

    density = compute_density_raster(features, grid, window_radius_m=50.0)

    assert (density == 0.0).all()


def test_all_touched_is_false_a_polygon_only_clipping_a_pixel_corner_does_not_count_it():
    """Deliberately different from distance_raster.py's all_touched=True:
    for area coverage, counting a pixel whose center isn't actually
    inside any feature would overstate density.
    """
    grid = _small_grid()
    # A tiny sliver polygon only touching the corner of pixel (0,0)
    # (x in [0,10], y in [40,50]) -- its center (5, 45) is not covered.
    sliver = box(9.9, 39.9, 10.1, 40.1)
    features = gpd.GeoDataFrame({"id": [1]}, geometry=[sliver], crs="EPSG:32645")

    density = compute_density_raster(features, grid, window_radius_m=10.0)

    assert density[0, 0] == 0.0


def test_reprojects_features_to_the_grid_crs_before_rasterizing(test_aoi):
    from app.data.grid import compute_aoi_grid

    grid = compute_aoi_grid(test_aoi.bounds_utm)
    center_lon = (TEST_AOI_BBOX_4326[0] + TEST_AOI_BBOX_4326[2]) / 2
    center_lat = (TEST_AOI_BBOX_4326[1] + TEST_AOI_BBOX_4326[3]) / 2
    building = box(center_lon - 0.0002, center_lat - 0.0002, center_lon + 0.0002, center_lat + 0.0002)
    features = gpd.GeoDataFrame({"id": [1]}, geometry=[building], crs="EPSG:4326")

    density = compute_density_raster(features, grid, window_radius_m=50.0)

    # If reprojection didn't happen, the (degree-sized) polygon would
    # cover essentially the whole (meter-sized) grid instead of a small
    # local patch near the AOI's center.
    assert 0.0 < density.mean() < 0.5
    assert density.max() > 0.0


# --- get_building_density: cached wrapper ---


def test_get_building_density_uses_get_osm_features_buildings_no_new_query(test_aoi, monkeypatch):
    calls = []

    def fake_get_osm_features(aoi):
        calls.append(aoi)
        b1 = box(85.3070, 27.7040, 85.3072, 27.7042)
        return OSMResult(
            buildings=gpd.GeoDataFrame({"id": [1]}, geometry=[b1], crs="EPSG:4326"),
            roads=gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326"),
            source_used="fake",
        )

    monkeypatch.setattr("app.data.density_raster.get_osm_features", fake_get_osm_features)

    result = get_building_density(test_aoi)

    assert len(calls) == 1
    assert result.attribution == OSM_ATTRIBUTION
    assert result.nodata is None
    assert result.density.shape == (result.grid.height, result.grid.width)
    assert result.density.max() > 0.0


def test_get_building_density_reads_window_radius_from_config(test_aoi, monkeypatch):
    def fake_get_osm_features(aoi):
        b1 = box(85.3070, 27.7040, 85.3072, 27.7042)
        return OSMResult(
            buildings=gpd.GeoDataFrame({"id": [1]}, geometry=[b1], crs="EPSG:4326"),
            roads=gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326"),
            source_used="fake",
        )

    monkeypatch.setattr("app.data.density_raster.get_osm_features", fake_get_osm_features)

    monkeypatch.setattr(config, "BUILDING_DENSITY_WINDOW_RADIUS_M", 20.0)
    small_window = get_building_density(test_aoi)

    monkeypatch.setattr(config, "BUILDING_DENSITY_WINDOW_RADIUS_M", 2000.0)
    large_window = get_building_density(test_aoi)

    # A larger window spreads the same building's coverage over more
    # pixels at a lower peak density -- and busts the cache (different
    # version), so this also confirms recalibrating the radius doesn't
    # silently reuse a stale result.
    assert not np.array_equal(small_window.density, large_window.density)
    assert small_window.density.max() > large_window.density.max()


def test_repeated_call_hits_the_processed_cache(test_aoi, monkeypatch):
    calls = []

    def fake_get_osm_features(aoi):
        calls.append(aoi)
        return OSMResult(
            buildings=gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326"),
            roads=gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326"),
            source_used="fake",
        )

    monkeypatch.setattr("app.data.density_raster.get_osm_features", fake_get_osm_features)

    first = get_building_density(test_aoi)
    second = get_building_density(test_aoi)

    assert len(calls) == 1
    assert np.array_equal(first.density, second.density)
