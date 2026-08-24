"""Tests for app/data/chirps.py -- local-hit / cloud-fallback
orchestration for the satellite precipitation source. Mirrors
test_soil.py's structure; simpler than that module's own tests since
CHIRPS's CRS is plain EPSG:4326 (no Homolosine-style reprojection-
before-windowing needed, unlike SoilGrids)."""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS

from app.data import config
from app.data.aoi import AOI
from app.data.attribution import CHIRPS_ATTRIBUTION
from app.data.chirps import CHIRPS_OUTPUT_NODATA, _whole_pixel_window, get_chirps_precipitation

WGS84 = CRS.from_epsg(4326)


def _write_fake_local_chirps_tif(path, aoi_bbox, fill_value=1500.0, nodata=-9999.0):
    """A tiny synthetic GeoTIFF covering `aoi_bbox`, in plain EPSG:4326 at
    a coarse ~0.05 degree-ish pixel size (matching CHIRPS's own real
    native resolution order of magnitude) -- written on the fly rather
    than a checked-in binary fixture, mirroring test_soil.py's own
    approach.
    """
    minx, miny, maxx, maxy = aoi_bbox
    width, height = 20, 20
    pixel_w = (maxx - minx) / width
    pixel_h = (maxy - miny) / height
    transform = Affine(pixel_w, 0, minx, 0, -pixel_h, maxy)
    array = np.full((height, width), fill_value, dtype=np.float32)
    array[0, 0] = nodata
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs=WGS84, transform=transform,
    ) as ds:
        # Deliberately NOT setting ds.nodata -- the real CHIRPS file
        # doesn't declare a NoData tag either (verified live, see
        # config.py's own comment); chirps.py must supply
        # config.CHIRPS_NODATA explicitly rather than read it off the
        # dataset, and this fixture is written to prove exactly that.
        ds.write(array, 1)


def test_local_hit_produces_precipitation_on_the_common_grid(test_aoi, monkeypatch, tmp_path):
    local_dir = tmp_path / "raw" / "chirps"
    local_dir.mkdir(parents=True)
    _write_fake_local_chirps_tif(local_dir / "fake_chirps.tif", test_aoi.bbox_4326)
    monkeypatch.setattr(config, "LOCAL_CHIRPS_DIR", local_dir)

    result = get_chirps_precipitation(test_aoi)

    assert result.source_used.startswith("local:")
    assert result.attribution == CHIRPS_ATTRIBUTION
    assert result.nodata == CHIRPS_OUTPUT_NODATA
    assert result.precipitation_mm.shape == (result.grid.height, result.grid.width)
    assert result.precipitation_mm.dtype == np.float32
    valid = result.precipitation_mm[result.precipitation_mm != CHIRPS_OUTPUT_NODATA]
    assert valid.size > 0
    # The fixture is a uniform 1500mm field (aside from one nodata corner
    # pixel) -- reprojection onto the UTM 45N analysis grid must preserve
    # that value.
    assert valid.mean() == pytest.approx(1500.0, abs=5.0)


def test_source_nodata_is_supplied_explicitly_not_read_off_the_dataset(test_aoi, monkeypatch, tmp_path):
    """The real thing this module exists to get right: the fixture above
    deliberately never calls rasterio's nodata= at write time (matching
    the real CHIRPS file's own undeclared NoData tag), and yet nodata
    pixels must still be masked out -- proving chirps.py's
    config.CHIRPS_NODATA is actually consulted, not silently skipped
    because `ds.nodata` came back None.
    """
    local_dir = tmp_path / "raw" / "chirps"
    local_dir.mkdir(parents=True)
    _write_fake_local_chirps_tif(local_dir / "fake_chirps.tif", test_aoi.bbox_4326)
    monkeypatch.setattr(config, "LOCAL_CHIRPS_DIR", local_dir)

    with rasterio.open(local_dir / "fake_chirps.tif") as ds:
        assert ds.nodata is None  # confirms the fixture matches the real file's own undeclared tag

    result = get_chirps_precipitation(test_aoi)

    # If nodata masking were silently skipped, the -9999 sentinel would
    # bilinear-blend into its neighbors instead of propagating as
    # CHIRPS_OUTPUT_NODATA, dragging the mean sharply negative.
    assert result.precipitation_mm.min() >= CHIRPS_OUTPUT_NODATA
    valid = result.precipitation_mm[result.precipitation_mm != CHIRPS_OUTPUT_NODATA]
    assert (valid > 0).all()


def test_repeated_call_for_same_aoi_hits_the_processed_cache(test_aoi, monkeypatch, tmp_path):
    local_dir = tmp_path / "raw" / "chirps"
    local_dir.mkdir(parents=True)
    _write_fake_local_chirps_tif(local_dir / "fake_chirps.tif", test_aoi.bbox_4326)
    monkeypatch.setattr(config, "LOCAL_CHIRPS_DIR", local_dir)

    first = get_chirps_precipitation(test_aoi)
    second = get_chirps_precipitation(test_aoi)

    assert np.array_equal(first.precipitation_mm, second.precipitation_mm, equal_nan=True)
    assert first.source_used == second.source_used


def _fake_chirps_window(bbox):
    minx, miny, maxx, maxy = bbox
    width, height = 20, 20
    pixel_w = (maxx - minx) / width
    pixel_h = (maxy - miny) / height
    transform = Affine(pixel_w, 0, minx, 0, -pixel_h, maxy)
    array = np.full((height, width), 1200.0, dtype=np.float32)
    return array, transform, WGS84


def test_falls_back_to_cloud_when_no_local_coverage(test_aoi, monkeypatch):
    """No local file at all (the default, per conftest's
    no_local_sources_by_default) -> clean fallback to the (mocked)
    cloud read, no error.
    """
    called = []

    def fake_fetch(aoi):
        called.append(aoi)
        return _fake_chirps_window(aoi.bbox_4326)

    monkeypatch.setattr("app.data.chirps._fetch_chirps_from_cloud", fake_fetch)

    result = get_chirps_precipitation(test_aoi)

    assert len(called) == 1
    assert result.source_used == "chirps:global_annual/1981-2024.44yrs"
    assert result.attribution == CHIRPS_ATTRIBUTION
    valid = result.precipitation_mm[result.precipitation_mm != CHIRPS_OUTPUT_NODATA]
    assert valid.size > 0
    assert valid.mean() == pytest.approx(1200.0, abs=5.0)


def test_falls_back_to_cloud_when_local_dir_has_no_covering_file(test_aoi, monkeypatch, tmp_path):
    empty_dir = tmp_path / "raw" / "chirps"
    empty_dir.mkdir(parents=True)
    monkeypatch.setattr(config, "LOCAL_CHIRPS_DIR", empty_dir)
    monkeypatch.setattr(
        "app.data.chirps._fetch_chirps_from_cloud", lambda aoi: _fake_chirps_window(aoi.bbox_4326)
    )

    result = get_chirps_precipitation(test_aoi)

    assert result.source_used == "chirps:global_annual/1981-2024.44yrs"


def test_fetch_from_cloud_opens_the_dataset_with_the_shared_retry_env(test_aoi, monkeypatch):
    """_fetch_chirps_from_cloud must open the dataset inside a
    rasterio.Env using config.GDAL_HTTP_RETRY_ENV -- the same transient-
    failure workaround dem.py/worldcover.py/soil.py's own fetch
    functions already rely on.
    """
    import app.data.chirps as chirps_module

    seen_env = {}
    original_env_cls = rasterio.Env

    class RecordingEnv(original_env_cls):
        def __init__(self, **kwargs):
            seen_env.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(rasterio, "Env", RecordingEnv)

    minx, miny, maxx, maxy = test_aoi.bbox_4326
    transform = Affine((maxx - minx) / 20, 0, minx, 0, -(maxy - miny) / 20, maxy)

    class FakeDataset:
        crs = WGS84

        def read(self, band, window):
            return np.full((20, 20), 1500.0, dtype=np.float32)

        @property
        def transform(self):
            return transform

        def window_transform(self, window):
            return transform

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(rasterio, "open", lambda url: FakeDataset())

    chirps_module._fetch_chirps_from_cloud(test_aoi)

    for key, value in config.GDAL_HTTP_RETRY_ENV.items():
        assert seen_env.get(key) == value


# --- _whole_pixel_window: a small AOI against CHIRPS's own coarse ~5.5km native pixels ---


def test_whole_pixel_window_expands_a_sub_pixel_aoi_to_at_least_one_pixel():
    """Regression test for a real bug caught live during implementation:
    a small (~2km) real test AOI against CHIRPS's real ~0.05 degree
    transform produced a raw `from_bounds` window of width=0.4,
    height=0.4 (source pixels) -- `ds.read()` rejected that outright
    with "Invalid dataset dimensions: 0 x 0" rather than rounding it to
    something usable. This is the exact transform/bbox pair that
    triggered it.
    """
    # CHIRPS's real transform: 0.05 degree pixels, origin at (-180, 50).
    transform = Affine(0.05, 0, -180.0, 0, -0.05, 50.0)
    aoi = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72))

    window = _whole_pixel_window(aoi, transform)

    assert window.width >= 1
    assert window.height >= 1


def test_whole_pixel_window_still_covers_a_multi_pixel_aoi_correctly():
    """A normal-sized AOI, spanning several CHIRPS pixels, must come back
    with the same whole-pixel bounds `from_bounds` itself would compute
    (just rounded outward to whole pixels) -- the fix must not shrink or
    misplace a window that was never the degenerate 0.4x0.4 case.
    """
    from rasterio.windows import from_bounds

    transform = Affine(0.05, 0, -180.0, 0, -0.05, 50.0)
    aoi = AOI(bbox_4326=(85.0, 27.0, 85.5, 27.5))  # ~50km, several real CHIRPS pixels wide

    raw = from_bounds(*aoi.bbox_4326, transform=transform)
    window = _whole_pixel_window(aoi, transform)

    assert window.col_off <= raw.col_off
    assert window.row_off <= raw.row_off
    assert window.col_off + window.width >= raw.col_off + raw.width
    assert window.row_off + window.height >= raw.row_off + raw.height
    assert window.width >= raw.width
    assert window.height >= raw.height


def test_get_chirps_precipitation_does_not_crash_for_an_aoi_smaller_than_one_source_pixel(
    test_aoi, monkeypatch, tmp_path
):
    """End-to-end version of the two _whole_pixel_window tests above:
    a local fixture whose own pixels are much coarser than test_aoi
    (mirroring CHIRPS's real ~5.5km native resolution against a small
    real AOI) must still produce a usable result through the full
    get_chirps_precipitation path, not just the isolated window helper.
    """
    minx, miny, maxx, maxy = test_aoi.bbox_4326
    # One coarse pixel roughly 10x wider/taller than the AOI itself.
    pad = (maxx - minx) * 5
    coarse_bounds = (minx - pad, miny - pad, maxx + pad, maxy + pad)

    local_dir = tmp_path / "raw" / "chirps"
    local_dir.mkdir(parents=True)
    path = local_dir / "coarse_fake_chirps.tif"
    cminx, cminy, cmaxx, cmaxy = coarse_bounds
    transform = Affine(cmaxx - cminx, 0, cminx, 0, -(cmaxy - cminy), cmaxy)
    with rasterio.open(
        path, "w", driver="GTiff", height=1, width=1, count=1,
        dtype="float32", crs=WGS84, transform=transform,
    ) as ds:
        ds.write(np.array([[1500.0]], dtype=np.float32), 1)
    monkeypatch.setattr(config, "LOCAL_CHIRPS_DIR", local_dir)

    result = get_chirps_precipitation(test_aoi)

    valid = result.precipitation_mm[result.precipitation_mm != CHIRPS_OUTPUT_NODATA]
    assert valid.size > 0
    assert valid.mean() == pytest.approx(1500.0, abs=5.0)


@pytest.mark.slow
def test_real_cloud_read_over_kathmandu():
    """Real network call against the actual UCSB-hosted CHIRPS annual-
    normals GeoTIFF -- confirms the live nodata handling and value range
    both work against the real dataset, not just a mock. Live-verified
    during implementation: this exact AOI reads back with a mean around
    1500mm, fully valid (no nodata) -- Kathmandu Valley is well inside
    CHIRPS's real coverage.
    """
    from app.data.aoi import AOI

    aoi = AOI(bbox_4326=(85.20, 27.60, 85.45, 27.80))

    result = get_chirps_precipitation(aoi)
    assert result.source_used == "chirps:global_annual/1981-2024.44yrs"
    valid = result.precipitation_mm[result.precipitation_mm != CHIRPS_OUTPUT_NODATA]
    assert valid.size > 0
    assert (valid > 0).all() and (valid < 10000).all()
