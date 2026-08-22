from __future__ import annotations

import numpy as np
import pytest
from affine import Affine

from app.data import config
from app.data.attribution import DEM_ATTRIBUTION
from app.data.dem import DEM_OUTPUT_NODATA, compute_slope_degrees, get_dem
from tests.data.conftest import FIXTURES_DIR


# --- compute_slope_degrees (Horn's method), tested in isolation from any file/network I/O ---


def test_compute_slope_degrees_on_a_known_45_degree_ramp_at_an_interior_pixel():
    # elevation rises exactly 1m per 1m of x. A 5x5 array gives pixel
    # (2,2) a full, unpadded 3x3 neighborhood, so Horn's method recovers
    # exactly 45 degrees there -- hand-verified: dz/dx=((3+6+3)-(1+2+1))/8
    # = 1.0, dz/dy=0, atan(1) = 45 degrees.
    cols = np.arange(5, dtype=np.float32)
    elevation = np.tile(cols, (5, 1))
    slope = compute_slope_degrees(elevation, resolution_m=1.0, nodata=-9999.0)
    assert slope[2, 2] == pytest.approx(45.0, abs=1e-3)


def test_compute_slope_degrees_edge_pixel_is_damped_by_edge_padding():
    # The border is estimated from an edge-replicated 3x3 window (the
    # standard convention absent real data beyond the raster edge), which
    # systematically underestimates a uniform gradient at the border
    # compared to the interior value -- hand-verified: dz/dx=((1+2+1)-
    # (0+0+0))/8=0.5, so atan(0.5) =~ 26.57 degrees, not 45.
    cols = np.arange(5, dtype=np.float32)
    elevation = np.tile(cols, (5, 1))
    slope = compute_slope_degrees(elevation, resolution_m=1.0, nodata=-9999.0)
    assert slope[0, 0] == pytest.approx(np.degrees(np.arctan(0.5)), abs=1e-3)
    assert slope[0, 0] < slope[2, 2]


def test_compute_slope_degrees_is_zero_on_flat_ground():
    elevation = np.full((4, 4), 1300.0, dtype=np.float32)
    slope = compute_slope_degrees(elevation, resolution_m=10.0, nodata=-9999.0)
    assert slope == pytest.approx(0.0, abs=1e-6)


def test_compute_slope_degrees_propagates_nodata_to_8_connected_neighbors():
    cols = np.arange(5, dtype=np.float32)
    elevation = np.tile(cols, (5, 1))
    elevation[2, 2] = -9999.0
    slope = compute_slope_degrees(elevation, resolution_m=1.0, nodata=-9999.0)

    # Horn's kernel is 8-connected: every pixel whose 3x3 window touches
    # the nodata center (rows/cols 1-3) must come out nodata too, not a
    # silently-wrong number.
    for r in (1, 2, 3):
        for c in (1, 2, 3):
            assert slope[r, c] == -9999.0, f"expected nodata at ({r},{c})"

    # A pixel 2 cells away in both directions never touches the nodata
    # pixel's window and must still be a real, finite value.
    assert slope[0, 0] != -9999.0


# --- local-hit path (fast, no network — real fixture file, real rasterio read) ---


def test_local_hit_produces_elevation_and_slope_on_the_common_grid(test_aoi, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_DEM_DIR", FIXTURES_DIR / "dem")

    result = get_dem(test_aoi)

    assert result.source_used.startswith("local:")
    assert result.attribution == DEM_ATTRIBUTION
    assert result.nodata == DEM_OUTPUT_NODATA
    assert result.elevation_m.shape == (result.grid.height, result.grid.width)
    assert result.slope_degrees.shape == result.elevation_m.shape
    assert result.grid.crs == "EPSG:32645"
    assert result.grid.resolution_m == 10.0
    # The fixture's elevation ramps from ~1300m upward; sanity-check the
    # resampled output landed in a plausible range rather than garbage.
    valid = result.elevation_m[result.elevation_m != DEM_OUTPUT_NODATA]
    assert valid.size > 0
    assert 1000.0 < valid.min() and valid.max() < 2000.0


def test_repeated_call_for_same_aoi_hits_the_processed_cache(test_aoi, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_DEM_DIR", FIXTURES_DIR / "dem")

    first = get_dem(test_aoi)
    second = get_dem(test_aoi)

    assert np.array_equal(first.elevation_m, second.elevation_m)
    assert second.source_used == first.source_used


# --- cloud-fallback path (mocked S3 call — no network) ---


def _fake_dem_tile():
    """A small synthetic 'S3 tile' covering the test AOI with margin, in
    EPSG:4326, matching what _fetch_dem_from_s3 would normally return.
    """
    array = np.full((40, 40), 1310.0, dtype=np.float32)
    transform = Affine(0.0005, 0, 85.30, 0, -0.0005, 27.72)  # covers ~(85.30-85.32, 27.70-27.72)
    return array, transform, "EPSG:4326", None


def test_falls_back_to_cloud_when_no_local_coverage(test_aoi, monkeypatch):
    """No local DEM directory at all (the default, per conftest's
    no_local_sources_by_default) -> clean fallback to the (mocked) S3
    path, no error.
    """
    called = []

    def fake_fetch(aoi):
        called.append(aoi)
        return _fake_dem_tile()

    monkeypatch.setattr("app.data.dem._fetch_dem_from_s3", fake_fetch)

    result = get_dem(test_aoi)

    assert len(called) == 1
    assert result.source_used == "s3://copernicus-dem-30m"
    assert result.attribution == DEM_ATTRIBUTION
    valid = result.elevation_m[result.elevation_m != DEM_OUTPUT_NODATA]
    assert valid.size > 0
    assert valid == pytest.approx(1310.0, abs=1e-3)


def test_falls_back_to_cloud_when_local_dir_has_no_covering_file(test_aoi, monkeypatch, tmp_path):
    # A local dir that exists but is empty is just as much "no local
    # coverage" as a missing directory entirely.
    empty_dir = tmp_path / "raw" / "dem"
    empty_dir.mkdir(parents=True)
    monkeypatch.setattr(config, "LOCAL_DEM_DIR", empty_dir)
    monkeypatch.setattr("app.data.dem._fetch_dem_from_s3", lambda aoi: _fake_dem_tile())

    result = get_dem(test_aoi)

    assert result.source_used == "s3://copernicus-dem-30m"


# --- real network integration test (occasional manual verification) ---


@pytest.mark.slow
def test_real_s3_read_over_kathmandu(test_aoi):
    result = get_dem(test_aoi)
    assert result.source_used == "s3://copernicus-dem-30m"
    valid = result.elevation_m[result.elevation_m != DEM_OUTPUT_NODATA]
    assert valid.size > 0
    # Kathmandu Durbar Square sits at roughly 1300-1350m elevation.
    assert 1000.0 < valid.mean() < 1600.0
