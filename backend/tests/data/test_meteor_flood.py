"""Tests for app/data/meteor_flood.py -- local-only orchestration for the
METEOR/Fathom flood hazard depth source. Mirrors test_chirps.py's
structure, with the local-hit path swapped for a hard-failure path
(DataSourceUnavailableError) instead of a cloud fallback, since this
source has none -- see meteor_flood.py's own module docstring for why.
"""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS

from app.data import config
from app.data.aoi import AOI
from app.data.attribution import METEOR_FLOOD_ATTRIBUTION
from app.data.errors import DataSourceUnavailableError
from app.data.meteor_flood import (
    METEOR_FLOOD_OUTPUT_NODATA,
    _whole_pixel_window,
    get_meteor_flood_hazard,
)

WGS84 = CRS.from_epsg(4326)


def _write_fake_local_meteor_tif(path, aoi_bbox, fill_value=0.8, sentinel=-9999.0, sentinel_frac=0.0):
    """A tiny synthetic GeoTIFF covering `aoi_bbox`, in plain EPSG:4326,
    mirroring test_chirps.py's own on-the-fly-fixture approach rather
    than a checked-in binary (the real 30 METEOR GeoTIFFs are ~300MB
    total and deliberately not committed -- see config.py's
    LOCAL_METEOR_FLOOD_DIR comment).
    """
    minx, miny, maxx, maxy = aoi_bbox
    width, height = 20, 20
    pixel_w = (maxx - minx) / width
    pixel_h = (maxy - miny) / height
    transform = Affine(pixel_w, 0, minx, 0, -pixel_h, maxy)
    array = np.full((height, width), fill_value, dtype=np.float32)
    n_sentinel = int(round(sentinel_frac * array.size))
    flat = array.reshape(-1)
    flat[:n_sentinel] = sentinel
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs=WGS84, transform=transform,
    ) as ds:
        # Deliberately NOT setting ds.nodata -- the real METEOR files
        # don't declare a NoData tag either (confirmed by direct
        # rasterio.open() inspection during implementation); both
        # sentinels are supplied explicitly via config.METEOR_FLOOD_NODATA_VALUES.
        ds.write(array, 1)


def _default_filename() -> str:
    return f"{config.METEOR_FLOOD_TYPE}_{config.METEOR_FLOOD_RETURN_PERIOD}.tif"


def test_local_hit_produces_depth_on_the_common_grid(test_aoi, monkeypatch, tmp_path):
    local_dir = tmp_path / "raw" / "meteor_flood"
    local_dir.mkdir(parents=True)
    _write_fake_local_meteor_tif(local_dir / _default_filename(), test_aoi.bbox_4326, fill_value=0.8)
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", local_dir)

    result = get_meteor_flood_hazard(test_aoi)

    assert result.source_used.startswith("local:")
    assert result.attribution == METEOR_FLOOD_ATTRIBUTION
    assert result.nodata == METEOR_FLOOD_OUTPUT_NODATA
    assert result.depth_m.shape == (result.grid.height, result.grid.width)
    assert result.depth_m.dtype == np.float32
    valid = result.depth_m[result.depth_m != METEOR_FLOOD_OUTPUT_NODATA]
    assert valid.size > 0
    assert valid.mean() == pytest.approx(0.8, abs=0.05)
    # A uniformly in-domain fixture must not trip the low-coverage warning.
    assert result.warning is None


def test_missing_local_file_raises_data_source_unavailable_error(test_aoi):
    """No local file at all (the default, per conftest's
    no_local_sources_by_default) -> a hard, clearly-worded failure, not a
    silent fallback -- this source has no cloud path to fall back to,
    unlike every other local-check-first module in this package.
    """
    with pytest.raises(DataSourceUnavailableError, match="cloud fallback"):
        get_meteor_flood_hazard(test_aoi)


def test_both_sentinel_values_are_masked_as_nodata(test_aoi, monkeypatch, tmp_path):
    """The real file's -9999.0 (outside model domain) and 999.0 (rarer
    masked value) sentinels must both be excluded before reprojection --
    if either leaked through as a real value, it would bilinear-blend
    into its neighbors and drag the mean wildly off from the true
    in-domain depth.
    """
    local_dir = tmp_path / "raw" / "meteor_flood"
    local_dir.mkdir(parents=True)
    path = local_dir / _default_filename()
    minx, miny, maxx, maxy = test_aoi.bbox_4326
    width, height = 20, 20
    pixel_w = (maxx - minx) / width
    pixel_h = (maxy - miny) / height
    transform = Affine(pixel_w, 0, minx, 0, -pixel_h, maxy)
    array = np.full((height, width), 0.5, dtype=np.float32)
    array[0, :] = -9999.0
    array[1, :] = 999.0
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs=WGS84, transform=transform,
    ) as ds:
        ds.write(array, 1)
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", local_dir)

    result = get_meteor_flood_hazard(test_aoi)

    valid = result.depth_m[result.depth_m != METEOR_FLOOD_OUTPUT_NODATA]
    assert valid.size > 0
    # If either sentinel leaked through unmasked, this would fail: -9999
    # would drag the mean sharply negative, 999 sharply positive.
    assert valid.mean() == pytest.approx(0.5, abs=0.1)
    assert (valid >= 0).all()
    assert (valid < 10).all()


def test_repeated_call_for_same_aoi_hits_the_processed_cache(test_aoi, monkeypatch, tmp_path):
    local_dir = tmp_path / "raw" / "meteor_flood"
    local_dir.mkdir(parents=True)
    _write_fake_local_meteor_tif(local_dir / _default_filename(), test_aoi.bbox_4326)
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", local_dir)

    first = get_meteor_flood_hazard(test_aoi)
    second = get_meteor_flood_hazard(test_aoi)

    assert np.array_equal(first.depth_m, second.depth_m, equal_nan=True)
    assert first.source_used == second.source_used


def test_low_in_domain_coverage_triggers_a_warning(test_aoi, monkeypatch, tmp_path):
    """An AOI that's almost entirely outside the Fathom model's domain
    (the normal case for hillslope/ridge terrain, not a data-quality
    bug) must surface a warning explaining why, mirroring twi/
    drainage_density/hand's own non-None-warning precedent.
    """
    local_dir = tmp_path / "raw" / "meteor_flood"
    local_dir.mkdir(parents=True)
    _write_fake_local_meteor_tif(
        local_dir / _default_filename(), test_aoi.bbox_4326, fill_value=0.5, sentinel_frac=0.98
    )
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", local_dir)

    result = get_meteor_flood_hazard(test_aoi)

    assert result.warning is not None
    assert "model" in result.warning.lower()


def test_meteor_flood_type_and_return_period_select_the_filename(test_aoi, monkeypatch, tmp_path):
    """A deployment can point at a different flood type/return period
    (e.g. Pluvial 1-in-20) via config, without any code change -- the
    module must look for exactly that file, not the FD/1in100 default.
    """
    local_dir = tmp_path / "raw" / "meteor_flood"
    local_dir.mkdir(parents=True)
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", local_dir)
    monkeypatch.setattr(config, "METEOR_FLOOD_TYPE", "P")
    monkeypatch.setattr(config, "METEOR_FLOOD_RETURN_PERIOD", "1in20")
    _write_fake_local_meteor_tif(local_dir / "P_1in20.tif", test_aoi.bbox_4326, fill_value=1.2)

    result = get_meteor_flood_hazard(test_aoi)

    assert result.source_used == "local:P_1in20.tif"
    valid = result.depth_m[result.depth_m != METEOR_FLOOD_OUTPUT_NODATA]
    assert valid.mean() == pytest.approx(1.2, abs=0.05)


# --- _whole_pixel_window: a small AOI against METEOR's coarse ~90m native pixels ---


def test_whole_pixel_window_expands_a_sub_pixel_aoi_to_at_least_one_pixel():
    """Same defensive fix as chirps.py's own regression test -- a tiny
    AOI against a coarse enough transform must never come back with a
    fractional (sub-1x1) window.
    """
    transform = Affine(0.000833333, 0, 85.0, 0, -0.000833333, 28.0)
    aoi = AOI(bbox_4326=(85.3000, 27.7000, 85.3003, 27.7003))

    window = _whole_pixel_window(aoi, transform)

    assert window.width >= 1
    assert window.height >= 1


def test_get_meteor_flood_hazard_does_not_crash_for_an_aoi_smaller_than_one_source_pixel(
    test_aoi, monkeypatch, tmp_path
):
    minx, miny, maxx, maxy = test_aoi.bbox_4326
    pad = (maxx - minx) * 5
    coarse_bounds = (minx - pad, miny - pad, maxx + pad, maxy + pad)

    local_dir = tmp_path / "raw" / "meteor_flood"
    local_dir.mkdir(parents=True)
    path = local_dir / _default_filename()
    cminx, cminy, cmaxx, cmaxy = coarse_bounds
    transform = Affine(cmaxx - cminx, 0, cminx, 0, -(cmaxy - cminy), cmaxy)
    with rasterio.open(
        path, "w", driver="GTiff", height=1, width=1, count=1,
        dtype="float32", crs=WGS84, transform=transform,
    ) as ds:
        ds.write(np.array([[0.4]], dtype=np.float32), 1)
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", local_dir)

    result = get_meteor_flood_hazard(test_aoi)

    valid = result.depth_m[result.depth_m != METEOR_FLOOD_OUTPUT_NODATA]
    assert valid.size > 0
    assert valid.mean() == pytest.approx(0.4, abs=0.05)
