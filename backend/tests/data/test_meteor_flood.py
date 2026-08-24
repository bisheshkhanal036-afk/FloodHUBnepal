"""Tests for app/data/meteor_flood.py -- local-only orchestration for the
METEOR/Fathom flood hazard depth source. Mirrors test_chirps.py's
structure, with the local-hit path swapped for a hard-failure path
(DataSourceUnavailableError) instead of a cloud fallback, since this
source has none -- see meteor_flood.py's own module docstring for why.
"""

from __future__ import annotations

import math

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
        # rasterio.open() inspection during implementation); both raw
        # sentinels are supplied explicitly via config.METEOR_FLOOD_RAW_SENTINELS.
        ds.write(array, 1)


def _default_filename() -> str:
    return f"{config.METEOR_FLOOD_TYPE}_{config.METEOR_FLOOD_RETURN_PERIOD}.tif"


def _write_padded_uniform_tif(path, aoi_bbox, fill_value, pad_factor=5):
    """A single-pixel GeoTIFF covering a bbox padded well beyond
    `aoi_bbox` on every side (same technique
    test_get_meteor_flood_hazard_does_not_crash_for_an_aoi_smaller_than_one_source_pixel
    already uses below) -- unlike _write_fake_local_meteor_tif's own
    exact-bbox-matching fixture, this gives bilinear resampling a full
    margin of real source data around every destination pixel, so a test
    using this can assert on literally every output pixel rather than a
    "valid" subset: reprojecting a small source raster whose extent
    exactly matches the AOI (no margin) leaves a genuine, expected sliver
    of dst_nodata at the destination grid's own edges -- a normal
    property of bilinear reprojection this project's other sources
    (chirps.py's own tests, e.g.) already work around the same way, by
    checking a "valid" subset rather than every pixel; padding sidesteps
    needing to do that here.
    """
    minx, miny, maxx, maxy = aoi_bbox
    pad = (maxx - minx) * pad_factor
    pminx, pminy, pmaxx, pmaxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    transform = Affine(pmaxx - pminx, 0, pminx, 0, -(pmaxy - pminy), pmaxy)
    with rasterio.open(
        path, "w", driver="GTiff", height=1, width=1, count=1,
        dtype="float32", crs=WGS84, transform=transform,
    ) as ds:
        ds.write(np.array([[fill_value]], dtype=np.float32), 1)


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
    # This criterion never attaches a warning any more -- see the module
    # docstring for why (there's no coverage gap left to warn about).
    assert result.warning is None


def test_missing_local_file_raises_data_source_unavailable_error(test_aoi):
    """No local file at all (the default, per conftest's
    no_local_sources_by_default) -> a hard, clearly-worded failure, not a
    silent fallback -- this source has no cloud path to fall back to,
    unlike every other local-check-first module in this package.
    """
    with pytest.raises(DataSourceUnavailableError, match="cloud fallback"):
        get_meteor_flood_hazard(test_aoi)


def test_outside_domain_sentinel_becomes_zero_depth_not_nodata(test_aoi, monkeypatch, tmp_path):
    """-9999.0 ("outside the Fathom model's simulated floodplain domain")
    must resolve to a real depth of 0.0m, not nodata -- this is the fix
    for the real bug reported live ("only the meteor area gets flood
    hazard output"): with the whole fixture set to this sentinel, every
    output pixel must still be classifiable, valued near 0.0, not
    excluded. Uses the padded single-pixel fixture (see
    _write_padded_uniform_tif's own docstring) so this can assert on
    literally every pixel, not just a "valid" subset.
    """
    local_dir = tmp_path / "raw" / "meteor_flood"
    local_dir.mkdir(parents=True)
    _write_padded_uniform_tif(local_dir / _default_filename(), test_aoi.bbox_4326, fill_value=-9999.0)
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", local_dir)

    result = get_meteor_flood_hazard(test_aoi)

    # No pixel should be nodata -- the whole point of this fix.
    assert not np.any(result.depth_m == METEOR_FLOOD_OUTPUT_NODATA)
    assert result.depth_m.mean() == pytest.approx(0.0, abs=0.01)
    assert result.warning is None


def test_permanent_water_sentinel_becomes_max_depth_not_zero(test_aoi, monkeypatch, tmp_path):
    """999.0 (the rarer masked/permanent-water sentinel) must NOT get the
    same treatment as -9999.0 -- mapping permanent water to a depth of
    0.0 would misclassify it as the lowest-risk case, a real correctness
    bug the fix above must not introduce. It resolves instead to this
    file's own observed maximum real depth (5.0m, `_PERMANENT_WATER_DEPTH_M`),
    landing in the same top risk_class as the worst real modeled cells.
    """
    local_dir = tmp_path / "raw" / "meteor_flood"
    local_dir.mkdir(parents=True)
    _write_padded_uniform_tif(local_dir / _default_filename(), test_aoi.bbox_4326, fill_value=999.0)
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", local_dir)

    result = get_meteor_flood_hazard(test_aoi)

    assert not np.any(result.depth_m == METEOR_FLOOD_OUTPUT_NODATA)
    assert result.depth_m.mean() == pytest.approx(5.0, abs=0.01)


def test_a_mix_of_both_sentinels_and_real_depth_resolves_distinctly(test_aoi, monkeypatch, tmp_path):
    """A single fixture mixing all three cases (outside-domain, permanent
    water, and real modeled depth) across different rows -- the resulting
    valid-pixel value range must span all three clusters distinctly (near
    0.0, near 0.5, near 5.0), confirming the two sentinels are told apart
    from each other and from real data, not conflated into one value.
    Uses the exact-bbox-matching fixture (not the padded one above,
    which can only represent a single uniform value) -- per
    _write_fake_local_meteor_tif's own docstring, this can leave a small
    genuine nodata fringe at the destination grid's edges from bilinear
    reprojection margin effects, so this checks the valid subset rather
    than asserting on every single pixel (same convention
    test_chirps.py's own tests already use for the same reason).
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
    array[0:6, :] = -9999.0  # outside model domain -> should become 0.0
    array[6:12, :] = 999.0  # permanent water -> should become 5.0
    # rows 12:20 stay the real 0.5m fixture value
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs=WGS84, transform=transform,
    ) as ds:
        ds.write(array, 1)
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", local_dir)

    result = get_meteor_flood_hazard(test_aoi)

    valid = result.depth_m[result.depth_m != METEOR_FLOOD_OUTPUT_NODATA]
    # The overwhelming majority of pixels must carry real data (this is
    # the fix itself) -- only a thin reprojection-margin fringe, if any,
    # may remain nodata.
    assert valid.size / result.depth_m.size > 0.9
    # Full observed value range spans all three cases: near 0.0 (former
    # -9999 rows), near 0.5 (real data), and near 5.0 (former 999 rows)
    # -- not collapsed together.
    assert valid.min() < 0.3
    assert valid.max() > 3.0
    assert np.any((valid > 0.3) & (valid < 3.0))


def test_repeated_call_for_same_aoi_hits_the_processed_cache(test_aoi, monkeypatch, tmp_path):
    local_dir = tmp_path / "raw" / "meteor_flood"
    local_dir.mkdir(parents=True)
    _write_fake_local_meteor_tif(local_dir / _default_filename(), test_aoi.bbox_4326)
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", local_dir)

    first = get_meteor_flood_hazard(test_aoi)
    second = get_meteor_flood_hazard(test_aoi)

    assert np.array_equal(first.depth_m, second.depth_m, equal_nan=True)
    assert first.source_used == second.source_used


def test_aoi_almost_entirely_outside_model_domain_still_gets_full_coverage(test_aoi, monkeypatch, tmp_path):
    """An AOI that's almost entirely outside the Fathom model's domain
    (the normal case for hillslope/ridge terrain) used to leave the
    criterion mostly nodata, with a warning explaining the gap -- the
    real bug the user reported ("only the meteor area gets flood hazard
    output"). Now: every pixel gets a real classification (the
    formerly-nodata majority resolves to 0.0m), and there is no warning
    left to attach.
    """
    local_dir = tmp_path / "raw" / "meteor_flood"
    local_dir.mkdir(parents=True)
    _write_fake_local_meteor_tif(
        local_dir / _default_filename(), test_aoi.bbox_4326, fill_value=0.5, sentinel_frac=0.98
    )
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", local_dir)

    result = get_meteor_flood_hazard(test_aoi)

    # Before this fix, a 98%-sentinel fixture like this one would have
    # left ~98% of the output nodata; now the overwhelming majority of
    # pixels carry real data (a thin reprojection-margin fringe aside --
    # see test_a_mix_of_both_sentinels_and_real_depth_resolves_distinctly's
    # own docstring for why this doesn't assert on literally every pixel).
    valid = result.depth_m[result.depth_m != METEOR_FLOOD_OUTPUT_NODATA]
    assert valid.size / result.depth_m.size > 0.9
    assert result.warning is None


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


def test_whole_pixel_window_adds_the_configured_margin_beyond_the_aoi():
    """Regression test for the second real bug caught live during
    implementation: a window cropped tightly to the AOI (no margin)
    starves bilinear resampling of neighboring source data at the
    destination grid's own edges, leaving a real fraction of the output
    at dst_nodata regardless of what the sentinels resolve to -- live-
    verified against the real FD_1in100.tif (a floodplain AOI went from
    99.9% to 100% valid coverage adding this margin). The window must be
    wider/taller than the raw from_bounds computation by exactly
    2 * _WINDOW_MARGIN_PX whole pixels (one margin's worth on each side).
    """
    from rasterio.windows import from_bounds

    from app.data.meteor_flood import _WINDOW_MARGIN_PX

    transform = Affine(0.000833333, 0, 85.0, 0, -0.000833333, 28.0)
    aoi = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72))  # several whole pixels wide, not sub-pixel

    raw = from_bounds(*aoi.bbox_4326, transform=transform)
    window = _whole_pixel_window(aoi, transform)

    # col_off/row_off move outward (lower) by the margin; width/height
    # grow by twice the margin (one side each way).
    assert window.col_off <= math.floor(raw.col_off) - _WINDOW_MARGIN_PX
    assert window.row_off <= math.floor(raw.row_off) - _WINDOW_MARGIN_PX
    assert window.width >= math.ceil(raw.width) + 2 * _WINDOW_MARGIN_PX - 1
    assert window.height >= math.ceil(raw.height) + 2 * _WINDOW_MARGIN_PX - 1


def test_get_meteor_flood_hazard_reaches_full_coverage_with_a_realistically_sized_fixture(
    test_aoi, monkeypatch, tmp_path
):
    """Unlike _write_padded_uniform_tif's own deliberately huge margin
    (5x the AOI's own width -- generous enough to pass even without the
    window-margin fix), this fixture is only a few native pixels larger
    than the AOI on each side, matching how much real headroom a small
    AOI actually has against METEOR's real ~90m-pixel national file at
    its own edges. Must still reach 100% valid coverage: the whole point
    of _WINDOW_MARGIN_PX is that a *realistic* amount of surrounding
    source data (not an artificially generous test fixture) is already
    enough.
    """
    minx, miny, maxx, maxy = test_aoi.bbox_4326
    # ~90m-equivalent native pixel size in degrees, matching METEOR's own
    # real resolution (config.py: 0.0008333... deg, "3 arcsecond").
    native_px_deg = 0.000833333
    pad = native_px_deg * 4  # a handful of native pixels of headroom, not 5x the AOI
    path = tmp_path / "raw" / "meteor_flood"
    path.mkdir(parents=True)
    file_path = path / _default_filename()

    pminx, pminy, pmaxx, pmaxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    width = height = 20
    transform = Affine((pmaxx - pminx) / width, 0, pminx, 0, -(pmaxy - pminy) / height, pmaxy)
    array = np.full((height, width), 0.5, dtype=np.float32)
    with rasterio.open(
        file_path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs=WGS84, transform=transform,
    ) as ds:
        ds.write(array, 1)
    monkeypatch.setattr(config, "LOCAL_METEOR_FLOOD_DIR", path)

    result = get_meteor_flood_hazard(test_aoi)

    assert not np.any(result.depth_m == METEOR_FLOOD_OUTPUT_NODATA)


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
