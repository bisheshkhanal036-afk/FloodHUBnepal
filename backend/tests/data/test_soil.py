from __future__ import annotations

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform_bounds

from app.data import config
from app.data.attribution import SOIL_ATTRIBUTION
from app.data.soil import SOIL_OUTPUT_NODATA, _scale_and_mask, get_soil_infiltration

# The real Interrupted Goode Homolosine CRS SoilGrids' VRT reports,
# verified live during implementation -- not EPSG:4326, unlike every
# other source module's cloud source in this project.
HOMOLOSINE_CRS = CRS.from_user_input(
    "+proj=igh +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs"
)


# --- _scale_and_mask: ISRIC's own documented conversion factor ---


def test_scale_and_mask_divides_raw_gkg_by_ten_to_get_percent():
    """Confirmed via ISRIC's own published SoilGrids conversion-factor
    table: sand's mapped unit is g/kg, conversion factor 10, conventional
    unit g/100g (%) -- see soil.py's own docstring.
    """
    raw = np.array([[500, 800]], dtype=np.int16)

    percent, _ = _scale_and_mask(raw, src_nodata=-32768)

    assert percent[0, 0] == pytest.approx(50.0)
    assert percent[0, 1] == pytest.approx(80.0)


def test_scale_and_mask_turns_source_nodata_into_nan_not_a_scaled_sentinel():
    """The real bug this exists to prevent: scaling -32768 (the raw
    nodata sentinel) by dividing by 10 first would silently produce
    -3276.8, a plausible-looking but completely wrong "percentage" that
    would then poison reprojection instead of being recognized as nodata.
    """
    raw = np.array([[500, -32768]], dtype=np.int16)

    percent, working_nodata = _scale_and_mask(raw, src_nodata=-32768)

    assert np.isnan(percent[0, 1])
    assert np.isnan(working_nodata)
    assert percent[0, 0] == pytest.approx(50.0)


# --- get_soil_infiltration: local-hit / cloud-fallback orchestration ---


def _write_fake_local_soil_tif(path):
    """A tiny synthetic GeoTIFF covering test_aoi's TEST_AOI_BBOX_4326, in
    the real Homolosine CRS (proving reprojection into a non-EPSG:4326
    source actually works end-to-end, not just that it's mocked away) --
    written on the fly rather than a checked-in binary fixture.
    """
    minx, miny, maxx, maxy = transform_bounds("EPSG:4326", HOMOLOSINE_CRS, 85.30, 27.70, 85.32, 27.72)
    width, height = 40, 40
    pixel_w = (maxx - minx) / width
    pixel_h = (maxy - miny) / height
    transform = Affine(pixel_w, 0, minx, 0, -pixel_h, maxy)
    array = np.full((height, width), 500, dtype=np.int16)  # 50% sand
    array[0, 0] = -32768
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="int16", crs=HOMOLOSINE_CRS, transform=transform, nodata=-32768,
    ) as ds:
        ds.write(array, 1)


def test_local_hit_produces_a_percentage_on_the_common_grid_via_homolosine_reprojection(test_aoi, monkeypatch, tmp_path):
    local_dir = tmp_path / "raw" / "soil"
    local_dir.mkdir(parents=True)
    _write_fake_local_soil_tif(local_dir / "fake_soilgrids.tif")
    monkeypatch.setattr(config, "LOCAL_SOIL_DIR", local_dir)

    result = get_soil_infiltration(test_aoi)

    assert result.source_used.startswith("local:")
    assert result.attribution == SOIL_ATTRIBUTION
    assert result.nodata == SOIL_OUTPUT_NODATA
    assert result.sand_pct.shape == (result.grid.height, result.grid.width)
    assert result.sand_pct.dtype == np.float32
    valid = result.sand_pct[result.sand_pct != SOIL_OUTPUT_NODATA]
    assert valid.size > 0
    # The fixture is a uniform 50% sand field (aside from one nodata
    # corner pixel) -- reprojecting from Homolosine onto the UTM 45N
    # analysis grid must preserve that value, not scramble it (the
    # symptom a seam-crossing or mis-windowed read would produce).
    assert valid.mean() == pytest.approx(50.0, abs=1.0)


def test_repeated_call_for_same_aoi_hits_the_processed_cache(test_aoi, monkeypatch, tmp_path):
    local_dir = tmp_path / "raw" / "soil"
    local_dir.mkdir(parents=True)
    _write_fake_local_soil_tif(local_dir / "fake_soilgrids.tif")
    monkeypatch.setattr(config, "LOCAL_SOIL_DIR", local_dir)

    first = get_soil_infiltration(test_aoi)
    second = get_soil_infiltration(test_aoi)

    assert np.array_equal(first.sand_pct, second.sand_pct, equal_nan=True)
    assert first.source_used == second.source_used


def _fake_soilgrids_window():
    minx, miny, maxx, maxy = transform_bounds("EPSG:4326", HOMOLOSINE_CRS, 85.30, 27.70, 85.32, 27.72)
    width, height = 40, 40
    pixel_w = (maxx - minx) / width
    pixel_h = (maxy - miny) / height
    transform = Affine(pixel_w, 0, minx, 0, -pixel_h, maxy)
    array = np.full((height, width), 300, dtype=np.int16)  # 30% sand
    return array, transform, HOMOLOSINE_CRS, -32768


def test_falls_back_to_cloud_when_no_local_coverage(test_aoi, monkeypatch):
    """No local file at all (the default, per conftest's
    no_local_sources_by_default) -> clean fallback to the (mocked)
    cloud/VRT read, no error.
    """
    called = []

    def fake_fetch(aoi):
        called.append(aoi)
        return _fake_soilgrids_window()

    monkeypatch.setattr("app.data.soil._fetch_sand_from_cloud", fake_fetch)

    result = get_soil_infiltration(test_aoi)

    assert len(called) == 1
    assert result.source_used == "isric:soilgrids/sand_0-5cm_mean"
    assert result.attribution == SOIL_ATTRIBUTION
    valid = result.sand_pct[result.sand_pct != SOIL_OUTPUT_NODATA]
    assert valid.size > 0
    assert valid.mean() == pytest.approx(30.0, abs=1.0)


def test_falls_back_to_cloud_when_local_dir_has_no_covering_file(test_aoi, monkeypatch, tmp_path):
    empty_dir = tmp_path / "raw" / "soil"
    empty_dir.mkdir(parents=True)
    monkeypatch.setattr(config, "LOCAL_SOIL_DIR", empty_dir)
    monkeypatch.setattr("app.data.soil._fetch_sand_from_cloud", lambda aoi: _fake_soilgrids_window())

    result = get_soil_infiltration(test_aoi)

    assert result.source_used == "isric:soilgrids/sand_0-5cm_mean"


def test_fetch_from_cloud_opens_the_dataset_with_the_shared_retry_env(test_aoi, monkeypatch):
    """_fetch_sand_from_cloud must open the VRT inside a rasterio.Env
    using config.GDAL_HTTP_RETRY_ENV -- the same transient-failure
    workaround dem.py/worldcover.py/population.py's own fetch functions
    already rely on (see config.py's own docstring).
    """
    import app.data.soil as soil_module

    seen_env = {}
    original_env_cls = rasterio.Env

    class RecordingEnv(original_env_cls):
        def __init__(self, **kwargs):
            seen_env.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(rasterio, "Env", RecordingEnv)

    minx, miny, maxx, maxy = transform_bounds("EPSG:4326", HOMOLOSINE_CRS, 85.30, 27.70, 85.32, 27.72)
    transform = Affine((maxx - minx) / 40, 0, minx, 0, -(maxy - miny) / 40, maxy)

    class FakeDataset:
        crs = HOMOLOSINE_CRS
        nodata = -32768

        def read(self, band, window):
            return np.full((40, 40), 500, dtype=np.int16)

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

    soil_module._fetch_sand_from_cloud(test_aoi)

    for key, value in config.GDAL_HTTP_RETRY_ENV.items():
        assert seen_env.get(key) == value


@pytest.mark.slow
def test_real_cloud_read_over_kathmandu():
    """Real network call against the actual ISRIC-hosted VRT -- confirms
    the Homolosine reprojection and g/kg -> % scaling both work against
    the live dataset, not just a mock.

    Deliberately does NOT use the shared `test_aoi` fixture (a tiny
    ~0.6km bbox around Kathmandu Durbar Square, sized for the DEM/
    WorldCover/OSM fixture rasters other tests share): verified live
    during implementation that this exact small bbox reads back as a
    3x4-pixel window at SoilGrids' real 250m resolution with ALL 12
    pixels genuinely nodata -- a real, small-scale gap in SoilGrids'
    own coverage for that specific spot, not a bug in this module (a
    wider window over the same valley, tried during implementation,
    came back ~74% valid). This test therefore uses a wider bbox across
    Kathmandu Valley, confirmed live to have real coverage.
    """
    from app.data.aoi import AOI

    wide_aoi = AOI(bbox_4326=(85.20, 27.60, 85.45, 27.80))

    result = get_soil_infiltration(wide_aoi)
    assert result.source_used == "isric:soilgrids/sand_0-5cm_mean"
    valid = result.sand_pct[result.sand_pct != SOIL_OUTPUT_NODATA]
    assert valid.size > 0
    assert (0.0 <= valid).all() and (valid <= 100.0).all()
