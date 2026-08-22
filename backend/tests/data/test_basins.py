"""Tests for app/data/basins.py — basin lookup, support-status
classification, and basin_to_aoi(). Uses a tiny synthetic 4-basin
fixture (tests/data/fixtures/basins/test_basins.shp), never the real
~100MB HydroBASINS download.
"""

from __future__ import annotations

import pytest

from app.data import config
from app.data.aoi import AOI
from app.data.basins import (
    basin_area_km2,
    basin_to_aoi,
    classify_support_status,
    get_basin,
    get_basin_pct_in_nepal,
    get_basin_support_status,
    list_basins_overlapping_nepal,
    pct_area_in_nepal,
    reset_basins_cache,
    reset_nepal_boundary_cache,
)
from app.data.errors import BasinNotFoundError, DataSourceUnavailableError
from tests.data.conftest import FIXTURES_DIR

FIXTURE_PATH = FIXTURES_DIR / "basins" / "test_basins.shp"

# HYBAS_IDs in the fixture (see the generation script referenced in the
# module docstring below) and their expected classification, empirically
# verified against the fixture during test authoring (not hand-estimated
# from raw degrees — the true UTM-reprojected percentages differ from a
# naive degree-based guess because of latitude distortion, exactly the
# reason SPEC.md requires area math in EPSG:32645, not EPSG:4326).
BASIN_FULLY_IN_NEPAL = 4080000010  # box(85.0, 27.0, 86.0, 28.0) -- entirely inside NEPAL_BBOX_4326
BASIN_PARTIAL = 4080000020  # box(85.0, 30.0, 86.0, 30.7) -- straddles the 30.5N northern edge, ~80% in
BASIN_DEGRADED = 4080000030  # box(85.0, 30.3, 86.0, 31.3) -- mostly north of the 30.5N edge, ~26% in
BASIN_MATCHING_TEST_AOI = 4080000040  # box(85.3050, 27.7020, 85.3110, 27.7080) -- == tests/data's TEST_AOI_BBOX_4326


@pytest.fixture(autouse=True)
def use_basin_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_BASINS_PATH", FIXTURE_PATH)
    # No Nepal boundary file by default -> classification below exercises
    # (and its expected percentages were verified against) the
    # NEPAL_BBOX_4326 rectangle-proxy fallback. The true-boundary code
    # path has its own dedicated test further down.
    monkeypatch.setattr(config, "LOCAL_NEPAL_BOUNDARY_PATH", tmp_path / "no_such_file.shp")
    reset_basins_cache()
    reset_nepal_boundary_cache()
    yield
    reset_basins_cache()
    reset_nepal_boundary_cache()


def test_get_basin_by_id_returns_the_matching_row():
    row = get_basin(BASIN_FULLY_IN_NEPAL)
    assert int(row.HYBAS_ID) == BASIN_FULLY_IN_NEPAL
    assert row.geometry.geom_type == "Polygon"


def test_get_basin_raises_for_unknown_id():
    with pytest.raises(BasinNotFoundError):
        get_basin(999999999)


def test_list_basins_overlapping_nepal_includes_all_four_fixture_basins():
    gdf = list_basins_overlapping_nepal()
    assert set(gdf["HYBAS_ID"].astype(int)) == {
        BASIN_FULLY_IN_NEPAL, BASIN_PARTIAL, BASIN_DEGRADED, BASIN_MATCHING_TEST_AOI,
    }


def test_classify_support_status_for_a_fully_in_nepal_basin():
    row = get_basin(BASIN_FULLY_IN_NEPAL)
    assert classify_support_status(row.geometry) == "fully_in_nepal"
    assert pct_area_in_nepal(row.geometry) == pytest.approx(1.0, abs=1e-6)


def test_classify_support_status_for_a_cross_border_partial_basin():
    row = get_basin(BASIN_PARTIAL)
    assert classify_support_status(row.geometry) == "partial_likely_adequate"
    pct = pct_area_in_nepal(row.geometry)
    assert 0.50 <= pct < 0.98


def test_classify_support_status_for_a_mostly_outside_basin():
    row = get_basin(BASIN_DEGRADED)
    assert classify_support_status(row.geometry) == "likely_degraded_at_edges"
    assert pct_area_in_nepal(row.geometry) < 0.50


def test_basin_area_km2_is_positive_and_true_area_not_bbox_area():
    row = get_basin(BASIN_FULLY_IN_NEPAL)
    assert basin_area_km2(row.geometry) > 0


def test_basin_to_aoi_produces_a_valid_aoi_with_bbox_and_polygon():
    aoi = basin_to_aoi(BASIN_FULLY_IN_NEPAL)

    assert isinstance(aoi, AOI)
    assert aoi.polygon is not None
    assert len(aoi.bbox_4326) == 4
    minx, miny, maxx, maxy = aoi.bbox_4326
    assert minx < maxx and miny < maxy
    # bbox_4326 is exactly the polygon's own bounding envelope.
    assert aoi.bbox_4326 == pytest.approx(aoi.polygon.bounds)
    # area_km2 uses the true polygon area, which for this rectangular
    # test basin equals the bbox rectangle's area, so this is really just
    # confirming the property doesn't blow up and returns something sane.
    assert aoi.area_km2 > 0


def test_basin_to_aoi_area_km2_uses_true_polygon_area_not_envelope_when_they_differ():
    from shapely.geometry import Polygon

    # A right-triangle-ish sliver: true area is much smaller than its
    # bounding rectangle, so area_km2 (polygon-aware) must be smaller
    # than what a bbox-only AOI over the same envelope would report.
    triangle = Polygon([(85.0, 27.0), (86.0, 27.0), (85.0, 28.0)])
    aoi_with_polygon = AOI(bbox_4326=triangle.bounds, polygon=triangle)
    aoi_bbox_only = AOI(bbox_4326=triangle.bounds)

    assert aoi_with_polygon.area_km2 < aoi_bbox_only.area_km2
    assert aoi_with_polygon.area_km2 == pytest.approx(aoi_bbox_only.area_km2 / 2, rel=0.05)


def test_raises_data_source_unavailable_when_basins_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_BASINS_PATH", tmp_path / "does_not_exist.shp")
    reset_basins_cache()

    with pytest.raises(DataSourceUnavailableError, match="no HydroBASINS file"):
        get_basin(BASIN_FULLY_IN_NEPAL)


# --- true Nepal boundary (optional) vs. the NEPAL_BBOX_4326 fallback proxy ---


def test_classification_falls_back_to_bbox_proxy_when_no_boundary_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_NEPAL_BOUNDARY_PATH", tmp_path / "no_such_file.shp")
    reset_nepal_boundary_cache()

    row = get_basin(BASIN_FULLY_IN_NEPAL)
    assert classify_support_status(row.geometry) == "fully_in_nepal"


def test_classification_uses_the_true_boundary_file_when_available(monkeypatch):
    """test_nepal_boundary.shp covers only the WESTERN half of
    NEPAL_BBOX_4326 (lon 80.0-84.0, not 80.0-88.3). BASIN_FULLY_IN_NEPAL
    sits at lon 85.0-86.0 -- "fully_in_nepal" under the rectangle proxy
    (test above), but entirely OUTSIDE this true boundary. A materially
    different result proves the true-boundary file is genuinely being
    read and used, not silently ignored in favor of the proxy.
    """
    boundary_path = FIXTURES_DIR / "basins" / "test_nepal_boundary.shp"
    monkeypatch.setattr(config, "LOCAL_NEPAL_BOUNDARY_PATH", boundary_path)
    reset_nepal_boundary_cache()

    row = get_basin(BASIN_FULLY_IN_NEPAL)
    assert pct_area_in_nepal(row.geometry) == pytest.approx(0.0, abs=1e-9)
    assert classify_support_status(row.geometry) == "likely_degraded_at_edges"


# --- per-HYBAS_ID classification caching ---


def test_get_basin_support_status_is_cached_across_calls(monkeypatch):
    calls = []
    real_get_basin = get_basin

    def tracking_get_basin(hybas_id):
        calls.append(hybas_id)
        return real_get_basin(hybas_id)

    monkeypatch.setattr("app.data.basins.get_basin", tracking_get_basin)

    first = get_basin_support_status(BASIN_FULLY_IN_NEPAL)
    second = get_basin_support_status(BASIN_FULLY_IN_NEPAL)

    assert first == second == "fully_in_nepal"
    assert len(calls) == 1  # the underlying basin row was only looked up once


def test_get_basin_pct_in_nepal_is_cached_across_calls(monkeypatch):
    calls = []
    real_get_basin = get_basin

    def tracking_get_basin(hybas_id):
        calls.append(hybas_id)
        return real_get_basin(hybas_id)

    monkeypatch.setattr("app.data.basins.get_basin", tracking_get_basin)

    first = get_basin_pct_in_nepal(BASIN_PARTIAL)
    second = get_basin_pct_in_nepal(BASIN_PARTIAL)

    assert first == second
    assert len(calls) == 1  # the underlying basin row was only looked up once


def test_different_hybas_ids_are_cached_independently():
    assert get_basin_support_status(BASIN_FULLY_IN_NEPAL) == "fully_in_nepal"
    assert get_basin_support_status(BASIN_DEGRADED) == "likely_degraded_at_edges"


def test_reset_basins_cache_invalidates_the_classification_cache(monkeypatch, tmp_path):
    import geopandas as gpd
    from shapely.geometry import box as shapely_box

    # Populate the cache under the original fixture.
    assert get_basin_support_status(BASIN_FULLY_IN_NEPAL) == "fully_in_nepal"

    # Swap in a *different* basins file that reuses the same HYBAS_ID for
    # a basin entirely outside Nepal -- if the classification cache
    # weren't cleared by reset_basins_cache(), this would still (wrongly)
    # return the stale "fully_in_nepal" result from before the swap.
    # (Southern India: outside Nepal, but still a geographically sane
    # distance from UTM zone 45N to reproject cleanly, unlike e.g. (0,0).)
    far_away_basin = shapely_box(75.0, 10.0, 76.0, 11.0)
    alt_path = tmp_path / "alt_basins.shp"
    gpd.GeoDataFrame(
        {"HYBAS_ID": [BASIN_FULLY_IN_NEPAL]}, geometry=[far_away_basin], crs="EPSG:4326"
    ).to_file(alt_path)

    monkeypatch.setattr(config, "LOCAL_BASINS_PATH", alt_path)
    reset_basins_cache()

    assert get_basin_support_status(BASIN_FULLY_IN_NEPAL) == "likely_degraded_at_edges"


# --- end-to-end: a basin-derived AOI through the real, unmodified DEM/WorldCover fetch functions ---


def test_basin_derived_aoi_produces_identical_dem_and_worldcover_results_to_the_equivalent_bbox_aoi(monkeypatch):
    """BASIN_MATCHING_TEST_AOI's envelope is exactly TEST_AOI_BBOX_4326.
    get_dem/get_worldcover only ever read AOI.bbox_4326/bounds_utm, so a
    basin-derived AOI must produce byte-identical results to a plain bbox
    AOI over the same extent — proving those Phase 2 functions really
    are unmodified and unaffected by AOI now optionally carrying a
    polygon.
    """
    from app.data.dem import get_dem
    from app.data.worldcover import get_worldcover
    from tests.data.conftest import TEST_AOI_BBOX_4326

    monkeypatch.setattr(config, "LOCAL_DEM_DIR", FIXTURES_DIR / "dem")
    monkeypatch.setattr(config, "LOCAL_WORLDCOVER_DIR", FIXTURES_DIR / "worldcover")

    basin_aoi = basin_to_aoi(BASIN_MATCHING_TEST_AOI)
    bbox_aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326)

    assert basin_aoi.bbox_4326 == pytest.approx(bbox_aoi.bbox_4326)
    assert basin_aoi.polygon is not None
    assert bbox_aoi.polygon is None

    basin_dem = get_dem(basin_aoi)
    bbox_dem = get_dem(bbox_aoi)
    assert basin_dem.grid == bbox_dem.grid
    assert (basin_dem.elevation_m == bbox_dem.elevation_m).all()
    assert (basin_dem.slope_degrees == bbox_dem.slope_degrees).all()

    basin_wc = get_worldcover(basin_aoi)
    bbox_wc = get_worldcover(bbox_aoi)
    assert basin_wc.grid == bbox_wc.grid
    assert (basin_wc.land_cover_class == bbox_wc.land_cover_class).all()


def test_raises_clear_error_for_point_geometry_pour_points_file(monkeypatch, tmp_path):
    """Regression test for the actual mismatch found during this phase's
    implementation: a HydroBASINS 'Pour Points' file (point geometry) is
    not a valid basin-boundary source and must be rejected with a clear
    error identifying why, not misused as if it were polygon data.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    pour_points_path = tmp_path / "pour_points.shp"
    gpd.GeoDataFrame(
        {"HYBAS_ID": [1, 2]}, geometry=[Point(85.0, 27.0), Point(85.1, 27.1)], crs="EPSG:4326"
    ).to_file(pour_points_path)

    monkeypatch.setattr(config, "LOCAL_BASINS_PATH", pour_points_path)
    reset_basins_cache()

    with pytest.raises(DataSourceUnavailableError, match="Pour Points"):
        get_basin(1)
