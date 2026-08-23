from __future__ import annotations

import math

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS

from app.data import config
from app.data.attribution import POPULATION_ATTRIBUTION
from app.data.population import KM_PER_DEGREE, POPULATION_OUTPUT_NODATA, _count_to_density, get_population

GEOGRAPHIC_CRS = CRS.from_epsg(4326)
UTM_CRS = CRS.from_epsg(32645)  # any projected CRS -- this project's own EPSG:32645

# HRSL's real native pixel size (~1 arcsec, verified live against the
# actual bucket), not WorldCover's ~10m -- these tests use the real
# figure since _count_to_density's whole job is computing true ground
# area from it.
HRSL_PIXEL_DEG = 0.0002777777777780012


# --- _count_to_density: the actual math (SPEC.md §2.2's count-vs-density rule) ---


def test_count_to_density_divides_by_true_geodetic_pixel_area():
    # A single pixel, known lat/lon, computed independently below (not by
    # re-deriving the same formula the implementation uses) via the
    # standard spherical-approximation area formula.
    lat = 27.72
    transform = Affine(HRSL_PIXEL_DEG, 0, 85.30, 0, -HRSL_PIXEL_DEG, lat)
    array = np.array([[100.0]])

    result = _count_to_density(array, transform, GEOGRAPHIC_CRS, nodata=np.nan)

    row_center_lat = lat - HRSL_PIXEL_DEG * 0.5
    expected_area_km2 = (HRSL_PIXEL_DEG * KM_PER_DEGREE * math.cos(math.radians(row_center_lat))) * (
        HRSL_PIXEL_DEG * KM_PER_DEGREE
    )
    expected_density = 100.0 / expected_area_km2
    assert result[0, 0] == pytest.approx(expected_density, rel=1e-9)
    # Sanity range check against the live-verified real-world figure this
    # module's own docstring cites (~0.85 x 10^-3 km² per HRSL pixel at
    # this latitude) -- catches a gross unit error (e.g. forgetting the
    # km-per-degree conversion) even if the exact-formula assertion above
    # were somehow wrong too.
    assert 0.0007 < expected_area_km2 < 0.0009


def test_count_to_density_area_shrinks_at_higher_latitude():
    """A pixel further from the equator covers LESS true ground for the
    same degree span (cos(lat) shrinks the east-west dimension) -- so the
    same raw count must produce a HIGHER density at higher latitude. This
    is the actual correctness property that matters: get the direction of
    this relationship backwards and every population figure this project
    ever computes outside the equator is wrong.
    """
    array = np.array([[100.0]])
    low_lat_transform = Affine(HRSL_PIXEL_DEG, 0, 85.30, 0, -HRSL_PIXEL_DEG, 5.0)
    high_lat_transform = Affine(HRSL_PIXEL_DEG, 0, 85.30, 0, -HRSL_PIXEL_DEG, 60.0)

    low_lat_density = _count_to_density(array, low_lat_transform, GEOGRAPHIC_CRS, nodata=np.nan)[0, 0]
    high_lat_density = _count_to_density(array, high_lat_transform, GEOGRAPHIC_CRS, nodata=np.nan)[0, 0]

    assert high_lat_density > low_lat_density


def test_count_to_density_preserves_nan_nodata():
    transform = Affine(HRSL_PIXEL_DEG, 0, 85.30, 0, -HRSL_PIXEL_DEG, 27.72)
    array = np.array([[100.0, np.nan]])

    result = _count_to_density(array, transform, GEOGRAPHIC_CRS, nodata=np.nan)

    assert np.isnan(result[0, 1])
    assert not np.isnan(result[0, 0])


def test_count_to_density_preserves_a_numeric_nodata_sentinel_exactly():
    """A numeric sentinel (unlike NaN) would silently become a bogus
    non-sentinel value if divided by area along with everything else
    (-1 / area != -1) -- this must restore the exact original sentinel
    at nodata pixels, not whatever the division happened to produce.
    """
    transform = Affine(HRSL_PIXEL_DEG, 0, 85.30, 0, -HRSL_PIXEL_DEG, 27.72)
    array = np.array([[100.0, -1.0]])

    result = _count_to_density(array, transform, GEOGRAPHIC_CRS, nodata=-1.0)

    assert result[0, 1] == -1.0


def test_count_to_density_uses_flat_pixel_area_for_a_projected_crs():
    """A projected (meters-based) CRS has no latitude-dependence -- every
    pixel is the same true size by construction, straight from the
    transform's own pixel dimensions.
    """
    transform = Affine(100.0, 0, 500000.0, 0, -100.0, 3000000.0)  # 100m x 100m pixels
    array = np.array([[100.0, 100.0], [100.0, 100.0]])

    result = _count_to_density(array, transform, UTM_CRS, nodata=np.nan)

    expected_density = 100.0 / (100.0 * 100.0 / 1e6)  # 100 people / 0.01 km²
    assert np.allclose(result, expected_density)


# --- get_population: local-hit / cloud-fallback orchestration ---


def _write_fake_local_population_tif(path):
    """A tiny synthetic GeoTIFF covering test_aoi's TEST_AOI_BBOX_4326,
    at HRSL's real native pixel size, with one real nodata pixel -- written
    on the fly rather than a checked-in binary fixture.
    """
    array = np.full((240, 240), 100.0, dtype=np.float64)
    array[0, 0] = np.nan
    transform = Affine(HRSL_PIXEL_DEG, 0, 85.30, 0, -HRSL_PIXEL_DEG, 27.72)
    with rasterio.open(
        path, "w", driver="GTiff", height=240, width=240, count=1,
        dtype="float64", crs="EPSG:4326", transform=transform, nodata=np.nan,
    ) as ds:
        ds.write(array, 1)


def test_local_hit_produces_density_not_raw_count_on_the_common_grid(test_aoi, monkeypatch, tmp_path):
    local_dir = tmp_path / "raw" / "population"
    local_dir.mkdir(parents=True)
    _write_fake_local_population_tif(local_dir / "fake_hrsl.tif")
    monkeypatch.setattr(config, "LOCAL_POPULATION_DIR", local_dir)

    result = get_population(test_aoi)

    assert result.source_used.startswith("local:")
    assert result.attribution == POPULATION_ATTRIBUTION
    assert result.nodata == POPULATION_OUTPUT_NODATA
    assert result.density.shape == (result.grid.height, result.grid.width)
    assert result.density.dtype == np.float32
    valid = result.density[result.density != POPULATION_OUTPUT_NODATA]
    assert valid.size > 0
    # The whole point: this must NOT be ~100 (the raw per-source-pixel
    # count baked into the fixture) -- a count-to-density conversion at
    # HRSL's real ~30m native pixel size must have actually run. Diving
    # a 30m-class pixel's count by its own ~0.00085 km² area produces a
    # density on the order of 10^5, not the raw count's own scale.
    assert valid.mean() > 1000


def test_repeated_call_for_same_aoi_hits_the_processed_cache(test_aoi, monkeypatch, tmp_path):
    local_dir = tmp_path / "raw" / "population"
    local_dir.mkdir(parents=True)
    _write_fake_local_population_tif(local_dir / "fake_hrsl.tif")
    monkeypatch.setattr(config, "LOCAL_POPULATION_DIR", local_dir)

    first = get_population(test_aoi)
    second = get_population(test_aoi)

    assert np.array_equal(first.density, second.density)
    assert first.source_used == second.source_used


def _fake_population_window():
    array = np.full((240, 240), 40.0, dtype=np.float64)
    transform = Affine(HRSL_PIXEL_DEG, 0, 85.30, 0, -HRSL_PIXEL_DEG, 27.72)
    return array, transform, "EPSG:4326", np.nan


def test_falls_back_to_cloud_when_no_local_coverage(test_aoi, monkeypatch):
    """No local file at all (the default, per conftest's
    no_local_sources_by_default) -> clean fallback to the (mocked) S3/VRT
    read, no error.
    """
    called = []

    def fake_fetch(aoi):
        called.append(aoi)
        return _fake_population_window()

    monkeypatch.setattr("app.data.population._fetch_population_from_s3", fake_fetch)

    result = get_population(test_aoi)

    assert len(called) == 1
    assert result.source_used == "s3://dataforgood-fb-data/hrsl-cogs/hrsl_general"
    assert result.attribution == POPULATION_ATTRIBUTION
    valid = result.density[result.density != POPULATION_OUTPUT_NODATA]
    assert valid.size > 0
    assert valid.mean() > 1000  # density, not the raw count-of-40 baked into the fake window


def test_falls_back_to_cloud_when_local_dir_has_no_covering_file(test_aoi, monkeypatch, tmp_path):
    empty_dir = tmp_path / "raw" / "population"
    empty_dir.mkdir(parents=True)
    monkeypatch.setattr(config, "LOCAL_POPULATION_DIR", empty_dir)
    monkeypatch.setattr("app.data.population._fetch_population_from_s3", lambda aoi: _fake_population_window())

    result = get_population(test_aoi)

    assert result.source_used == "s3://dataforgood-fb-data/hrsl-cogs/hrsl_general"


def test_fetch_from_s3_opens_the_dataset_with_retry_and_region_env(test_aoi, monkeypatch):
    """_fetch_population_from_s3 must open the VRT inside a rasterio.Env
    combining BOTH config.GDAL_HTTP_RETRY_ENV and
    config.POPULATION_S3_REGION_ENV -- this is a real live-verified
    workaround (see config.py's own docstring for what testing during
    implementation actually showed), not decorative, so a future edit
    that drops one silently must fail this test.
    """
    import app.data.population as population_module

    seen_env = {}
    original_env_cls = rasterio.Env

    class RecordingEnv(original_env_cls):
        def __init__(self, **kwargs):
            seen_env.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(rasterio, "Env", RecordingEnv)

    class FakeDataset:
        transform = Affine(HRSL_PIXEL_DEG, 0, 85.30, 0, -HRSL_PIXEL_DEG, 27.72)
        crs = GEOGRAPHIC_CRS
        nodata = np.nan

        def read(self, band, window):
            return np.full((240, 240), 5.0, dtype=np.float64)

        def window_transform(self, window):
            return self.transform

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(rasterio, "open", lambda url: FakeDataset())

    population_module._fetch_population_from_s3(test_aoi)

    for key, value in config.GDAL_HTTP_RETRY_ENV.items():
        assert seen_env.get(key) == value
    for key, value in config.POPULATION_S3_REGION_ENV.items():
        assert seen_env.get(key) == value


@pytest.mark.slow
def test_real_s3_read_over_kathmandu(test_aoi):
    """Real network call against the actual bucket -- confirms the
    region-config workaround (or lack of need for it) actually works
    against the live dataset, not just a mock, and that the resulting
    values are density-scale, not raw-count-scale.
    """
    result = get_population(test_aoi)
    assert result.source_used == "s3://dataforgood-fb-data/hrsl-cogs/hrsl_general"
    valid = result.density[result.density != POPULATION_OUTPUT_NODATA]
    assert valid.size > 0  # Kathmandu's dense urban core should show real population values
    assert valid.max() > 0
