from __future__ import annotations

import shutil

import geopandas as gpd
import pytest

from app.data import config
from app.data.attribution import OSM_ATTRIBUTION
from app.data.errors import DataSourceUnavailableError
from app.data.osm import (
    _find_local_pbf,
    _local_processed_path,
    get_osm_features,
    get_waterways,
    reset_local_osm_parser_cache,
)
from tests.data.conftest import FIXTURES_DIR

FIXTURE_PBF = FIXTURES_DIR / "osm" / "nepal-test-extract.osm.pbf"
WATERWAY_FIXTURE_PBF = FIXTURES_DIR / "osm" / "nepal-test-extract-waterway.osm.pbf"


def _use_local_pbf(monkeypatch, tmp_path, fixture_path, subdir="osm_local"):
    """Points config.LOCAL_OSM_DIR at a fresh directory containing only a
    copy of `fixture_path` -- _find_local_pbf() globs a whole directory
    (see osm.py's own docstring for why), and the two OSM fixtures live
    side by side in FIXTURES_DIR/osm/, so a test that wants a specific
    one active needs it alone in its own directory, not ambiguously
    alongside the other.
    """
    local_dir = tmp_path / subdir
    local_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(fixture_path, local_dir / fixture_path.name)
    monkeypatch.setattr(config, "LOCAL_OSM_DIR", local_dir)
    reset_local_osm_parser_cache()


# --- _find_local_pbf: directory glob, not one fixed filename ---


def test_find_local_pbf_returns_none_when_directory_is_empty_or_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_OSM_DIR", tmp_path / "does_not_exist")
    assert _find_local_pbf() is None

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr(config, "LOCAL_OSM_DIR", empty_dir)
    assert _find_local_pbf() is None


def test_find_local_pbf_ignores_non_pbf_files(monkeypatch, tmp_path):
    d = tmp_path / "osm"
    d.mkdir()
    (d / "readme.txt").write_text("not a pbf")
    monkeypatch.setattr(config, "LOCAL_OSM_DIR", d)
    assert _find_local_pbf() is None


def test_find_local_pbf_picks_the_most_recently_modified_file_regardless_of_name_sort_order(monkeypatch, tmp_path):
    """A real downloaded extract's filename carries its own date (e.g.
    "nepal-260821.osm.pbf") -- if an older extract is left in place next
    to a newer one, the newer one (by modification time) must win, even
    if it would sort alphabetically *before* the older one.
    """
    d = tmp_path / "osm"
    d.mkdir()
    older = d / "z-newer-name-but-older-date.osm.pbf"
    newer = d / "a-older-name-but-newer-date.osm.pbf"
    older.write_bytes(b"fake")
    newer.write_bytes(b"fake")
    import os
    import time

    now = time.time()
    os.utime(older, (now - 100, now - 100))
    os.utime(newer, (now, now))
    monkeypatch.setattr(config, "LOCAL_OSM_DIR", d)

    assert _find_local_pbf() == newer


# --- _local_processed_path / tier 1 (pre-processed local FlatGeobuf) ---


def _write_fgb(path, geometries, **props):
    from shapely.geometry import base as shapely_base

    if isinstance(geometries, shapely_base.BaseGeometry):
        geometries = [geometries]
    gdf = gpd.GeoDataFrame({k: [v] * len(geometries) for k, v in props.items()}, geometry=geometries, crs="EPSG:4326")
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="FlatGeobuf")


def test_local_processed_path_returns_none_when_directory_or_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_OSM_PROCESSED_DIR", tmp_path / "does_not_exist")
    assert _local_processed_path("buildings.fgb") is None

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr(config, "LOCAL_OSM_PROCESSED_DIR", empty_dir)
    assert _local_processed_path("buildings.fgb") is None


def test_local_processed_path_finds_the_exact_named_file(monkeypatch, tmp_path):
    d = tmp_path / "processed"
    d.mkdir()
    (d / "buildings.fgb").write_bytes(b"fake")
    monkeypatch.setattr(config, "LOCAL_OSM_PROCESSED_DIR", d)

    assert _local_processed_path("buildings.fgb") == d / "buildings.fgb"
    assert _local_processed_path("roads.fgb") is None  # only buildings.fgb exists in this dir


def test_processed_local_hit_bbox_filters_a_real_fgb_file(test_aoi, monkeypatch, tmp_path):
    """A real (if tiny) FlatGeobuf file written with geopandas, containing
    one building inside TEST_AOI_BBOX_4326 and one well outside it -- this
    exercises the actual bbox= spatial filter end to end, not just "the
    file was read".
    """
    from shapely.geometry import Point

    d = tmp_path / "processed"
    inside = Point(85.3070, 27.7040).buffer(0.0001)  # inside TEST_AOI_BBOX_4326
    outside = Point(0.0, 0.0).buffer(0.0001)  # nowhere near it
    _write_fgb(d / "buildings.fgb", [inside, outside])
    _write_fgb(d / "roads.fgb", [])
    monkeypatch.setattr(config, "LOCAL_OSM_PROCESSED_DIR", d)

    result = get_osm_features(test_aoi)

    assert result.source_used == "local_processed"
    assert result.attribution == OSM_ATTRIBUTION
    assert len(result.buildings) == 1  # the outside one must be filtered out by bbox=


def test_processed_local_hit_used_for_waterways_too(test_aoi, monkeypatch, tmp_path):
    from shapely.geometry import LineString

    d = tmp_path / "processed"
    inside = LineString([(85.306, 27.703), (85.306, 27.707)])
    _write_fgb(d / "waterways.fgb", [inside])
    monkeypatch.setattr(config, "LOCAL_OSM_PROCESSED_DIR", d)

    result = get_waterways(test_aoi)

    assert result.source_used == "local_processed"
    assert len(result.waterways) == 1


def test_processed_local_takes_priority_over_the_raw_pbf_when_both_are_present(test_aoi, monkeypatch, tmp_path):
    """Tier 1 must win over tier 2 -- there's no reason to pay the slow
    .pbf parse when the fast pre-processed extract is right there too.
    """
    _use_local_pbf(monkeypatch, tmp_path, FIXTURE_PBF)  # tier 2 present, has 1 building/1 road
    d = tmp_path / "processed"
    from shapely.geometry import Point

    _write_fgb(d / "buildings.fgb", [Point(85.3070, 27.7040).buffer(0.0001)] * 2)  # deliberately != tier 2's count
    _write_fgb(d / "roads.fgb", [])
    monkeypatch.setattr(config, "LOCAL_OSM_PROCESSED_DIR", d)

    result = get_osm_features(test_aoi)

    assert result.source_used == "local_processed"
    assert len(result.buildings) == 2  # tier 1's count, not tier 2's (which would be 1)


def test_falls_through_to_pbf_when_only_one_of_buildings_roads_fgb_is_present(test_aoi, monkeypatch, tmp_path):
    """get_osm_features requires BOTH buildings.fgb and roads.fgb to use
    tier 1 -- mirrors _fetch_from_r2 requiring both R2 URLs together.
    A directory with only one of the two must fall through to tier 2/3,
    not silently use a missing file.
    """
    _use_local_pbf(monkeypatch, tmp_path, FIXTURE_PBF)
    d = tmp_path / "processed"
    from shapely.geometry import Point

    _write_fgb(d / "buildings.fgb", [Point(85.3070, 27.7040).buffer(0.0001)])  # roads.fgb deliberately missing
    monkeypatch.setattr(config, "LOCAL_OSM_PROCESSED_DIR", d)

    result = get_osm_features(test_aoi)

    assert result.source_used.startswith("local:")  # fell through to tier 2, not tier 1


# --- local-hit path (fast, no network — real tiny .pbf, real pyrosm parse) ---


def test_local_hit_parses_the_real_fixture_pbf(test_aoi, monkeypatch, tmp_path):
    """tests/data/fixtures/osm/nepal-test-extract.osm.pbf is a real, valid
    (if tiny) .osm.pbf file containing one building and one road inside
    TEST_AOI_BBOX_4326 — generated with pyosmium, not mocked, so this
    test exercises the actual pyrosm parsing path end to end.
    """
    _use_local_pbf(monkeypatch, tmp_path, FIXTURE_PBF)

    result = get_osm_features(test_aoi)

    assert result.source_used.startswith("local:")
    assert result.attribution == OSM_ATTRIBUTION
    assert isinstance(result.buildings, gpd.GeoDataFrame)
    assert isinstance(result.roads, gpd.GeoDataFrame)
    assert len(result.buildings) == 1
    assert len(result.roads) == 1
    assert result.buildings.iloc[0]["building"] == "yes"


def test_repeated_call_for_same_aoi_hits_the_processed_cache(test_aoi, monkeypatch, tmp_path):
    _use_local_pbf(monkeypatch, tmp_path, FIXTURE_PBF)

    first = get_osm_features(test_aoi)
    second = get_osm_features(test_aoi)

    assert len(first.buildings) == len(second.buildings)
    assert first.source_used == second.source_used


# --- _read_remote_fgb: bbox-filtered remote read + error translation ---
# (mocks pyogrio.read_dataframe directly -- no real network call)


def test_read_remote_fgb_passes_the_aoi_bbox_through_to_pyogrio(test_aoi, monkeypatch):
    import pyogrio

    from app.data.osm import _read_remote_fgb

    calls = []

    def fake_read_dataframe(url, bbox):
        calls.append((url, bbox))
        return _fake_buildings_gdf()

    monkeypatch.setattr(pyogrio, "read_dataframe", fake_read_dataframe)

    result = _read_remote_fgb("https://example-r2.dev/buildings.fgb", test_aoi)

    assert calls == [("https://example-r2.dev/buildings.fgb", test_aoi.bbox_4326)]
    assert len(result) == 1


def test_read_remote_fgb_translates_pyogrio_datasourceerror(test_aoi, monkeypatch):
    """A network/access failure from pyogrio (unreachable host, 403, a
    bucket that doesn't exist, etc.) must surface as this module's own
    DataSourceUnavailableError, not pyogrio's own exception type leaking
    out of osm.py's public functions.
    """
    import pyogrio

    from app.data.osm import _read_remote_fgb

    def failing_read_dataframe(url, bbox):
        raise pyogrio.errors.DataSourceError("CURL error: Could not resolve host")

    monkeypatch.setattr(pyogrio, "read_dataframe", failing_read_dataframe)

    with pytest.raises(DataSourceUnavailableError, match="Could not resolve host"):
        _read_remote_fgb("https://example-r2.dev/buildings.fgb", test_aoi)


# --- R2 fallback path (mocked — no network) ---


def _fake_buildings_gdf():
    from shapely.geometry import Point

    return gpd.GeoDataFrame({"id": [1]}, geometry=[Point(85.307, 27.704).buffer(0.0001)], crs="EPSG:4326")


def _fake_roads_gdf():
    from shapely.geometry import LineString

    return gpd.GeoDataFrame(
        {"id": [1]}, geometry=[LineString([(85.308, 27.705), (85.3085, 27.7055)])], crs="EPSG:4326"
    )


def test_falls_back_to_r2_when_no_local_pbf(test_aoi, monkeypatch):
    """No local .pbf at all (the default, per conftest's
    no_local_sources_by_default) -> clean fallback to the (mocked) R2
    path, no error.
    """
    monkeypatch.setattr(config, "OSM_R2_BUILDINGS_URL", "https://example-r2.dev/nepal_buildings.geojson")
    monkeypatch.setattr(config, "OSM_R2_ROADS_URL", "https://example-r2.dev/nepal_roads.geojson")

    called = []

    def fake_fetch(aoi):
        called.append(aoi)
        return _fake_buildings_gdf(), _fake_roads_gdf()

    monkeypatch.setattr("app.data.osm._fetch_from_r2", fake_fetch)

    result = get_osm_features(test_aoi)

    assert len(called) == 1
    assert result.source_used == "r2"
    assert result.attribution == OSM_ATTRIBUTION
    assert len(result.buildings) == 1
    assert len(result.roads) == 1


def test_raises_explicit_error_when_neither_local_nor_r2_available(test_aoi):
    """Both the local .pbf and R2 are unavailable (conftest's
    no_local_sources_by_default already clears OSM_R2_*_URL) -> a clear,
    explicit error, not a silent fallthrough to a live query (Overpass is
    never used in the request path, per the brief).
    """
    with pytest.raises(DataSourceUnavailableError, match="R2 fallback is not configured"):
        get_osm_features(test_aoi)


def test_raises_explicit_error_when_r2_configured_but_fetch_fails(test_aoi, monkeypatch):
    monkeypatch.setattr(config, "OSM_R2_BUILDINGS_URL", "https://example-r2.dev/nepal_buildings.geojson")
    monkeypatch.setattr(config, "OSM_R2_ROADS_URL", "https://example-r2.dev/nepal_roads.geojson")

    def failing_fetch(aoi):
        raise DataSourceUnavailableError("osm: R2 fallback fetch failed: simulated network error")

    monkeypatch.setattr("app.data.osm._fetch_from_r2", failing_fetch)

    with pytest.raises(DataSourceUnavailableError, match="simulated network error"):
        get_osm_features(test_aoi)


# --- get_waterways: local-hit path (fast, no network — real tiny .pbf, real pyrosm parse) ---


def test_waterways_local_hit_parses_the_real_fixture_pbf(test_aoi, monkeypatch, tmp_path):
    """tests/data/fixtures/osm/nepal-test-extract-waterway.osm.pbf is a
    real, valid .osm.pbf (generated by scripts/generate_waterway_fixture.py)
    containing one waterway=river way inside TEST_AOI_BBOX_4326 — a
    separate fixture from the buildings/roads one, so this phase's
    addition can never affect get_osm_features' own test assertions.
    """
    _use_local_pbf(monkeypatch, tmp_path, WATERWAY_FIXTURE_PBF)

    result = get_waterways(test_aoi)

    assert result.source_used.startswith("local:")
    assert result.attribution == OSM_ATTRIBUTION
    assert isinstance(result.waterways, gpd.GeoDataFrame)
    assert len(result.waterways) == 1
    assert result.waterways.iloc[0]["waterway"] == "river"


def test_waterways_repeated_call_for_same_aoi_hits_the_processed_cache(test_aoi, monkeypatch, tmp_path):
    _use_local_pbf(monkeypatch, tmp_path, WATERWAY_FIXTURE_PBF)

    first = get_waterways(test_aoi)
    second = get_waterways(test_aoi)

    assert len(first.waterways) == len(second.waterways)
    assert first.source_used == second.source_used


def test_waterways_cached_separately_from_buildings_and_roads(test_aoi, monkeypatch, tmp_path):
    """get_osm_features and get_waterways must not share a cache entry —
    they're different queries against the same underlying source.
    """
    _use_local_pbf(monkeypatch, tmp_path, FIXTURE_PBF, subdir="osm_local_buildings")
    osm_result = get_osm_features(test_aoi)

    _use_local_pbf(monkeypatch, tmp_path, WATERWAY_FIXTURE_PBF, subdir="osm_local_waterway")
    waterways_result = get_waterways(test_aoi)

    assert len(osm_result.buildings) == 1
    assert len(waterways_result.waterways) == 1


def test_get_osm_features_and_get_waterways_share_one_parse_for_the_same_aoi(test_aoi, monkeypatch, tmp_path):
    """The whole point of _load_local_osm's shared cache: when both
    get_osm_features and get_waterways are needed for the same (file,
    AOI), the underlying pyrosm OSM object is only constructed once, not
    once per call. A real Nepal-wide extract's first low-level parse is
    the expensive part (~145s, measured live against a real 412MB
    file); this fixture is tiny, so the point here is the *call count*,
    not the timing.
    """
    _use_local_pbf(monkeypatch, tmp_path, FIXTURE_PBF)
    # Also drop the waterway fixture in the same directory, so both
    # get_osm_features and get_waterways resolve to the same local file.
    shutil.copy(WATERWAY_FIXTURE_PBF, config.LOCAL_OSM_DIR / WATERWAY_FIXTURE_PBF.name)

    calls = []
    import pyrosm

    original_init = pyrosm.OSM.__init__

    def tracking_init(self, *args, **kwargs):
        calls.append(1)
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(pyrosm.OSM, "__init__", tracking_init)

    get_osm_features(test_aoi)
    get_waterways(test_aoi)

    # Both calls resolve to the same (most-recently-modified) local file
    # in a directory containing both fixtures -- so this also implicitly
    # confirms _find_local_pbf()'s "most recently modified wins" choice
    # doesn't itself cause a second, different file to be opened.
    assert len(calls) == 1


# --- get_waterways: R2 fallback path (mocked — no network) ---


def _fake_waterways_gdf():
    from shapely.geometry import LineString

    return gpd.GeoDataFrame(
        {"waterway": ["river"]}, geometry=[LineString([(85.306, 27.703), (85.306, 27.707)])], crs="EPSG:4326"
    )


def test_waterways_falls_back_to_r2_when_no_local_pbf(test_aoi, monkeypatch):
    monkeypatch.setattr(config, "OSM_R2_WATERWAYS_URL", "https://example-r2.dev/nepal_waterways.geojson")

    called = []

    def fake_fetch(aoi):
        called.append(aoi)
        return _fake_waterways_gdf()

    monkeypatch.setattr("app.data.osm._fetch_waterways_from_r2", fake_fetch)

    result = get_waterways(test_aoi)

    assert len(called) == 1
    assert result.source_used == "r2"
    assert result.attribution == OSM_ATTRIBUTION
    assert len(result.waterways) == 1


def test_waterways_raises_explicit_error_when_neither_local_nor_r2_available(test_aoi):
    with pytest.raises(DataSourceUnavailableError, match="R2 fallback is not configured"):
        get_waterways(test_aoi)


def test_waterways_raises_explicit_error_when_r2_configured_but_fetch_fails(test_aoi, monkeypatch):
    monkeypatch.setattr(config, "OSM_R2_WATERWAYS_URL", "https://example-r2.dev/nepal_waterways.geojson")

    def failing_fetch(aoi):
        raise DataSourceUnavailableError("osm: R2 fallback fetch failed: simulated network error")

    monkeypatch.setattr("app.data.osm._fetch_waterways_from_r2", failing_fetch)

    with pytest.raises(DataSourceUnavailableError, match="simulated network error"):
        get_waterways(test_aoi)


# --- real network integration test (occasional manual verification) ---


@pytest.mark.slow
@pytest.mark.skipif(
    not config.OSM_R2_BUILDINGS_URL or not config.OSM_R2_ROADS_URL,
    reason="R2 bucket not configured (set OSM_R2_BUILDINGS_URL / OSM_R2_ROADS_URL) yet",
)
def test_real_r2_read_over_kathmandu(test_aoi):
    result = get_osm_features(test_aoi)
    assert result.source_used == "r2"
    assert len(result.buildings) > 0


@pytest.mark.slow
@pytest.mark.skipif(
    not config.OSM_R2_WATERWAYS_URL, reason="R2 bucket not configured (set OSM_R2_WATERWAYS_URL) yet"
)
def test_waterways_real_r2_read_over_kathmandu(test_aoi):
    result = get_waterways(test_aoi)
    assert result.source_used == "r2"
