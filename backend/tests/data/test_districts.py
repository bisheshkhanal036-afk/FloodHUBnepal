"""Tests for app/data/districts.py — district lookup and
district_to_aoi(). Uses a tiny synthetic 3-district fixture
(tests/data/fixtures/basins/test_districts.shp, same directory the basin
fixtures live in), never the real HDX COD-AB download.
"""

from __future__ import annotations

import pytest

from app.data import config
from app.data.aoi import AOI
from app.data.districts import (
    district_area_km2,
    district_to_aoi,
    get_district,
    list_districts,
    reset_districts_cache,
)
from app.data.errors import DataSourceUnavailableError, DistrictNotFoundError
from tests.data.conftest import FIXTURES_DIR

FIXTURE_PATH = FIXTURES_DIR / "basins" / "test_districts.shp"

DISTRICT_A = "NP9901"  # box(85.0, 27.0, 85.2, 27.2), "Testpur"
DISTRICT_B = "NP9902"  # box(84.0, 28.0, 84.3, 28.3), "Testganj"
DISTRICT_MATCHING_TEST_AOI = "NP9903"  # box(85.3050, 27.7020, 85.3110, 27.7080) -- == tests/data's TEST_AOI_BBOX_4326


@pytest.fixture(autouse=True)
def use_districts_fixture(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_ADMIN_DISTRICTS_PATH", FIXTURE_PATH)
    reset_districts_cache()
    yield
    reset_districts_cache()


def test_get_district_by_pcode_returns_the_matching_row():
    row = get_district(DISTRICT_A)
    assert str(row.adm2_pcode) == DISTRICT_A
    assert str(row.adm2_name) == "Testpur"
    assert str(row.adm1_name) == "TestProvince"
    assert row.geometry.geom_type == "Polygon"


def test_get_district_raises_for_unknown_pcode():
    with pytest.raises(DistrictNotFoundError):
        get_district("NP0000")


def test_list_districts_includes_all_three_fixture_districts():
    gdf = list_districts()
    assert set(gdf["adm2_pcode"].astype(str)) == {DISTRICT_A, DISTRICT_B, DISTRICT_MATCHING_TEST_AOI}


def test_district_area_km2_is_positive():
    row = get_district(DISTRICT_A)
    assert district_area_km2(row.geometry) > 0


def test_district_to_aoi_produces_a_valid_aoi_with_bbox_and_polygon():
    aoi = district_to_aoi(DISTRICT_A)

    assert isinstance(aoi, AOI)
    assert aoi.polygon is not None
    assert len(aoi.bbox_4326) == 4
    minx, miny, maxx, maxy = aoi.bbox_4326
    assert minx < maxx and miny < maxy
    assert aoi.bbox_4326 == pytest.approx(aoi.polygon.bounds)
    assert aoi.area_km2 > 0


def test_raises_data_source_unavailable_when_districts_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_ADMIN_DISTRICTS_PATH", tmp_path / "does_not_exist.shp")
    reset_districts_cache()

    with pytest.raises(DataSourceUnavailableError, match="no admin-boundaries file"):
        get_district(DISTRICT_A)


def test_raises_clear_error_when_required_columns_are_missing(monkeypatch, tmp_path):
    import geopandas as gpd
    from shapely.geometry import box

    bad_path = tmp_path / "bad_districts.shp"
    gpd.GeoDataFrame({"some_other_col": [1]}, geometry=[box(85.0, 27.0, 85.1, 27.1)], crs="EPSG:4326").to_file(
        bad_path
    )

    monkeypatch.setattr(config, "LOCAL_ADMIN_DISTRICTS_PATH", bad_path)
    reset_districts_cache()

    with pytest.raises(DataSourceUnavailableError, match="missing column"):
        get_district(DISTRICT_A)


# --- end-to-end: a district-derived AOI through the real, unmodified DEM/WorldCover fetch functions ---


def test_district_derived_aoi_produces_identical_dem_and_worldcover_results_to_the_equivalent_bbox_aoi(monkeypatch):
    """DISTRICT_MATCHING_TEST_AOI's envelope is exactly TEST_AOI_BBOX_4326
    -- mirrors test_basins.py's own basin-vs-bbox parity test, proving
    district_to_aoi's output is just as unmodified-consumer-safe as
    basin_to_aoi's.
    """
    from app.data.dem import get_dem
    from app.data.worldcover import get_worldcover
    from tests.data.conftest import TEST_AOI_BBOX_4326

    monkeypatch.setattr(config, "LOCAL_DEM_DIR", FIXTURES_DIR / "dem")
    monkeypatch.setattr(config, "LOCAL_WORLDCOVER_DIR", FIXTURES_DIR / "worldcover")

    district_aoi = district_to_aoi(DISTRICT_MATCHING_TEST_AOI)
    bbox_aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326)

    assert district_aoi.bbox_4326 == pytest.approx(bbox_aoi.bbox_4326)
    assert district_aoi.polygon is not None
    assert bbox_aoi.polygon is None

    district_dem = get_dem(district_aoi)
    bbox_dem = get_dem(bbox_aoi)
    assert district_dem.grid == bbox_dem.grid
    assert (district_dem.elevation_m == bbox_dem.elevation_m).all()

    district_wc = get_worldcover(district_aoi)
    bbox_wc = get_worldcover(bbox_aoi)
    assert district_wc.grid == bbox_wc.grid
    assert (district_wc.land_cover_class == bbox_wc.land_cover_class).all()
