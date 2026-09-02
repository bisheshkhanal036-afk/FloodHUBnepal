"""Tests for app/data/validation_extent.py -- local-only orchestration
for real, satellite-observed flood-extent polygons used to validate a
computed risk surface. Mirrors basins.py/meteor_flood.py's own
local-only-no-cloud-fallback shape.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from app.data import config
from app.data.aoi import AOI
from app.data.errors import DataSourceUnavailableError
from app.data.validation_extent import get_observed_flood_mask, get_validation_extent_geojson, list_validation_events

WGS84 = "EPSG:4326"

# Captured at collection time, before the autouse no-local-sources-by-
# default fixture (tests/data/conftest.py) monkeypatches
# config.VALIDATION_EVENTS to {} for every individual test -- that
# isolation is correct (a test shouldn't silently depend on the real
# downloaded/digitized shapefiles), but it means the real dict can only
# be inspected here, at import time, not from inside a test function.
_REAL_VALIDATION_EVENTS = dict(config.VALIDATION_EVENTS)


def _write_fake_flood_extent_shp(path, polygons):
    gdf = gpd.GeoDataFrame({"geometry": polygons}, crs=WGS84)
    gdf.to_file(path)


def _register_event(monkeypatch, tmp_path, key, filename, attribution="Fake attribution"):
    local_dir = tmp_path / "raw" / "validation_extents"
    local_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "LOCAL_VALIDATION_EXTENTS_DIR", local_dir)
    monkeypatch.setattr(
        config,
        "VALIDATION_EVENTS",
        {key: {"label": f"Fake event {key}", "path": filename, "attribution": attribution}},
    )
    return local_dir


def test_list_validation_events_reflects_config(monkeypatch):
    monkeypatch.setattr(
        config,
        "VALIDATION_EVENTS",
        {"a": {"label": "Event A", "path": "a.shp", "attribution": "x"}, "b": {"label": "Event B", "path": "b.shp", "attribution": "x"}},
    )
    assert list_validation_events() == {"a": "Event A", "b": "Event B"}


def test_local_hit_rasterizes_the_flood_polygon_onto_the_aoi_grid(test_aoi, monkeypatch, tmp_path):
    local_dir = _register_event(monkeypatch, tmp_path, "fake_event", "fake_event.shp", "UNOSAT fake — CC BY-SA")
    # A polygon covering the left half of test_aoi's own bbox only, so the
    # rasterized mask isn't trivially all-0 or all-1.
    minx, miny, maxx, maxy = test_aoi.bbox_4326
    half_flood = box(minx, miny, (minx + maxx) / 2, maxy)
    _write_fake_flood_extent_shp(local_dir / "fake_event.shp", [half_flood])

    result = get_observed_flood_mask(test_aoi, "fake_event")

    assert result.event == "fake_event"
    assert result.attribution == "UNOSAT fake — CC BY-SA"
    assert result.observed_flooded.shape == (result.grid.height, result.grid.width)
    assert result.observed_flooded.dtype == np.uint8
    assert set(np.unique(result.observed_flooded)) <= {0, 1}
    # Roughly half the grid should be flagged flooded (the left half) --
    # not exact, since the AOI's own grid may not split evenly at 10m.
    flooded_fraction = result.observed_flooded.mean()
    assert 0.35 < flooded_fraction < 0.65


def test_aoi_entirely_outside_the_flood_polygon_returns_an_all_zero_mask(test_aoi, monkeypatch, tmp_path):
    local_dir = _register_event(monkeypatch, tmp_path, "fake_event", "fake_event.shp")
    # A polygon far from test_aoi -- no overlap at all.
    far_away = box(10.0, 10.0, 10.1, 10.1)
    _write_fake_flood_extent_shp(local_dir / "fake_event.shp", [far_away])

    result = get_observed_flood_mask(test_aoi, "fake_event")

    assert result.observed_flooded.sum() == 0


def test_unrecognized_event_raises_data_source_unavailable_error(test_aoi, monkeypatch):
    monkeypatch.setattr(config, "VALIDATION_EVENTS", {})

    with pytest.raises(DataSourceUnavailableError, match="unrecognized event"):
        get_observed_flood_mask(test_aoi, "not_a_real_event")


def test_missing_local_file_raises_data_source_unavailable_error(test_aoi, monkeypatch, tmp_path):
    _register_event(monkeypatch, tmp_path, "fake_event", "does_not_exist.shp")

    with pytest.raises(DataSourceUnavailableError, match="no local flood-extent shapefile"):
        get_observed_flood_mask(test_aoi, "fake_event")


# --- multi-file events: `path` as a list, e.g. nepal_2026_emsr927
# (config.py), registered as ONE toggleable event backed by 3 separate
# Copernicus EMS AOI shapefiles rather than 3 separate event keys. ---


def _register_multi_file_event(monkeypatch, tmp_path, key, filenames, attribution="Fake attribution"):
    local_dir = tmp_path / "raw" / "validation_extents"
    local_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "LOCAL_VALIDATION_EXTENTS_DIR", local_dir)
    monkeypatch.setattr(
        config,
        "VALIDATION_EVENTS",
        {key: {"label": f"Fake multi-file event {key}", "path": filenames, "attribution": attribution}},
    )
    return local_dir


def test_multi_file_event_merges_all_paths_into_one_mask(test_aoi, monkeypatch, tmp_path):
    local_dir = _register_multi_file_event(monkeypatch, tmp_path, "fake_multi", ["left.shp", "right.shp"])
    minx, miny, maxx, maxy = test_aoi.bbox_4326
    midx = (minx + maxx) / 2
    _write_fake_flood_extent_shp(local_dir / "left.shp", [box(minx, miny, midx, maxy)])
    _write_fake_flood_extent_shp(local_dir / "right.shp", [box(midx, miny, maxx, maxy)])

    result = get_observed_flood_mask(test_aoi, "fake_multi")

    # The two halves together should cover essentially the whole AOI --
    # if only one file's polygon were actually being read, this would be
    # ~0.5, not ~1.0.
    assert result.observed_flooded.mean() > 0.9


def test_multi_file_event_missing_one_of_several_files_lists_it_by_name(test_aoi, monkeypatch, tmp_path):
    local_dir = _register_multi_file_event(monkeypatch, tmp_path, "fake_multi", ["present.shp", "missing.shp"])
    _write_fake_flood_extent_shp(local_dir / "present.shp", [box(0, 0, 1, 1)])

    with pytest.raises(DataSourceUnavailableError, match="missing.shp"):
        get_observed_flood_mask(test_aoi, "fake_multi")


def test_multi_file_event_geojson_combines_all_paths_into_one_feature_collection(monkeypatch, tmp_path):
    get_validation_extent_geojson.cache_clear()
    local_dir = _register_multi_file_event(monkeypatch, tmp_path, "fake_multi", ["a.shp", "b.shp"])
    _write_fake_flood_extent_shp(local_dir / "a.shp", [box(85.30, 27.70, 85.31, 27.71)])
    _write_fake_flood_extent_shp(local_dir / "b.shp", [box(85.32, 27.72, 85.33, 27.73)])

    geojson = get_validation_extent_geojson("fake_multi")

    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 2


def test_multi_file_event_independently_reprojects_each_file_before_merging(test_aoi, monkeypatch, tmp_path):
    """The two files in a multi-file event need not share one native CRS
    -- this project's own registered events already don't (mbrsc is
    EPSG:32644, rasuwa_2026 is EPSG:32645) -- so each must be reprojected
    on its own before merging, not just once assuming a shared CRS.
    """
    local_dir = _register_multi_file_event(monkeypatch, tmp_path, "fake_multi", ["wgs84.shp", "utm.shp"])
    minx, miny, maxx, maxy = test_aoi.bbox_4326
    midx = (minx + maxx) / 2
    left_4326 = box(minx, miny, midx, maxy)
    right_4326 = box(midx, miny, maxx, maxy)
    _write_fake_flood_extent_shp(local_dir / "wgs84.shp", [left_4326])
    right_utm = gpd.GeoDataFrame({"geometry": [right_4326]}, crs=WGS84).to_crs("EPSG:32645")
    right_utm.to_file(local_dir / "utm.shp")

    result = get_observed_flood_mask(test_aoi, "fake_multi")

    assert result.observed_flooded.mean() > 0.9


def test_repeated_call_for_same_aoi_hits_the_processed_cache(test_aoi, monkeypatch, tmp_path):
    local_dir = _register_event(monkeypatch, tmp_path, "fake_event", "fake_event.shp")
    minx, miny, maxx, maxy = test_aoi.bbox_4326
    _write_fake_flood_extent_shp(local_dir / "fake_event.shp", [box(minx, miny, maxx, maxy)])

    first = get_observed_flood_mask(test_aoi, "fake_event")
    second = get_observed_flood_mask(test_aoi, "fake_event")

    assert np.array_equal(first.observed_flooded, second.observed_flooded)


def test_source_shapefile_in_a_non_wgs84_crs_is_reprojected_before_rasterizing(test_aoi, monkeypatch, tmp_path):
    """Every prior test here writes its fixture shapefile in WGS84
    (EPSG:4326), the same CRS get_observed_flood_mask's own `if gdf.crs
    is not None and str(gdf.crs) != grid.crs: gdf = gdf.to_crs(...)`
    branch was never actually exercised against a real mismatch by. Two
    of the three real events added alongside this test are natively UTM
    (nepal_2024_west_mbrsc: EPSG:32644, rasuwa_2026: EPSG:32645, both
    confirmed live via a direct geopandas read before registering them
    in config.py) -- this closes that real gap rather than trusting the
    reprojection branch worked by inference.
    """
    local_dir = _register_event(monkeypatch, tmp_path, "fake_event", "fake_event.shp")
    minx, miny, maxx, maxy = test_aoi.bbox_4326
    half_flood_4326 = box(minx, miny, (minx + maxx) / 2, maxy)
    utm_gdf = gpd.GeoDataFrame({"geometry": [half_flood_4326]}, crs=WGS84).to_crs("EPSG:32645")
    utm_gdf.to_file(local_dir / "fake_event.shp")

    result = get_observed_flood_mask(test_aoi, "fake_event")

    assert result.observed_flooded.shape == (result.grid.height, result.grid.width)
    flooded_fraction = result.observed_flooded.mean()
    assert 0.35 < flooded_fraction < 0.65


def test_partial_edge_overlap_pixel_is_not_counted_as_flooded(test_aoi, monkeypatch, tmp_path):
    """all_touched=False, deliberately: a pixel only merely clipped by
    the flood polygon's own edge should not be flagged flooded, the same
    reasoning density_raster.py's own building-coverage rasterization
    already applies (as opposed to distance_raster.py's all_touched=True,
    which is correct only for measuring distance to a thin line, not
    membership in an area).
    """
    local_dir = _register_event(monkeypatch, tmp_path, "fake_event", "fake_event.shp")
    minx, miny, maxx, maxy = test_aoi.bbox_4326
    # A sliver polygon far thinner than one 10m pixel, along the AOI's
    # own left edge -- with all_touched=False this should rasterize to
    # (at most) a thin, small fraction of flooded pixels, not a solid
    # column the way all_touched=True would produce.
    sliver = box(minx, miny, minx + 0.00001, maxy)
    _write_fake_flood_extent_shp(local_dir / "fake_event.shp", [sliver])

    result = get_observed_flood_mask(test_aoi, "fake_event")

    # A solid all_touched=True column spanning the AOI's full height would
    # flag every row (grid.height, ~60 for this AOI at 10m resolution);
    # all_touched=False against a sub-pixel-width sliver should flag only
    # a small handful of pixels whose center the sliver happens to cross,
    # not anywhere near the full column.
    assert result.observed_flooded.sum() < result.grid.height / 2


# --- get_validation_extent_geojson: the map-display counterpart to
# get_observed_flood_mask's own validation-math use of the same file.
# lru_cache-based (no AOI to key by, unlike everything else in this
# module) -- .cache_clear() at the start of every test here so one
# test's fixture registered under "fake_event" can never leak a stale
# cached result into the next test that reuses that same key. ---


def test_extent_geojson_is_a_real_feature_collection(monkeypatch, tmp_path):
    get_validation_extent_geojson.cache_clear()
    local_dir = _register_event(monkeypatch, tmp_path, "fake_event", "fake_event.shp")
    _write_fake_flood_extent_shp(local_dir / "fake_event.shp", [box(85.30, 27.70, 85.32, 27.72)])

    geojson = get_validation_extent_geojson("fake_event")

    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 1
    assert geojson["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    # Geometry-only -- no attribute columns carried through (also sidesteps
    # a real non-JSON-serializable-datetime-column issue the actual
    # UNOSAT shapefile has, confirmed live during implementation).
    assert geojson["features"][0]["properties"] == {}


def test_extent_geojson_result_is_cached_across_calls(monkeypatch, tmp_path):
    get_validation_extent_geojson.cache_clear()
    local_dir = _register_event(monkeypatch, tmp_path, "fake_event", "fake_event.shp")
    _write_fake_flood_extent_shp(local_dir / "fake_event.shp", [box(85.30, 27.70, 85.32, 27.72)])

    first = get_validation_extent_geojson("fake_event")
    # Delete the source file entirely -- a cache hit must not need it.
    (local_dir / "fake_event.shp").unlink()
    second = get_validation_extent_geojson("fake_event")

    assert first == second


def test_extent_geojson_unrecognized_event_raises_data_source_unavailable_error(monkeypatch):
    get_validation_extent_geojson.cache_clear()
    monkeypatch.setattr(config, "VALIDATION_EVENTS", {})

    with pytest.raises(DataSourceUnavailableError, match="unrecognized event"):
        get_validation_extent_geojson("not_a_real_event")


def test_extent_geojson_missing_local_file_raises_data_source_unavailable_error(monkeypatch, tmp_path):
    get_validation_extent_geojson.cache_clear()
    _register_event(monkeypatch, tmp_path, "fake_event", "does_not_exist.shp")

    with pytest.raises(DataSourceUnavailableError, match="no local flood-extent shapefile"):
        get_validation_extent_geojson("fake_event")


# --- The REAL, unmocked config.VALIDATION_EVENTS -- a lightweight guard
# against exactly the kind of typo (a missing key, an empty path/label)
# that a config-only change like registering a new event can introduce
# without ever tripping the synthetic-fixture tests above, since those
# always build their own well-formed fake dict. Deliberately does NOT
# open any of the real local shapefiles (which are large, gitignored,
# one-time downloads/digitizations not present in CI -- same reasoning
# every other real-data source in this package keeps its own live
# verification out of the automated suite, per SPEC.md's own "All
# automated tests still use a small synthetic fixture, never the real
# downloads" convention) -- only the dict shape itself.
def test_real_validation_events_config_is_well_formed():
    assert len(_REAL_VALIDATION_EVENTS) >= 1
    seen_paths = set()
    for key, meta in _REAL_VALIDATION_EVENTS.items():
        assert isinstance(key, str) and key
        for field in ("label", "attribution"):
            assert isinstance(meta.get(field), str) and meta[field].strip(), f"{key}.{field} is missing or blank"
        # `path` is normally a single filename, but an event can also
        # register a LIST of filenames (e.g. nepal_2026_emsr927, one
        # toggleable event backed by 3 separate Copernicus EMS AOI
        # shapefiles) -- validation_extent.py's _resolve_event_paths
        # accepts either shape, so this check must too.
        raw_path = meta.get("path")
        paths = raw_path if isinstance(raw_path, list) else [raw_path]
        assert paths, f"{key}.path is empty"
        for p in paths:
            assert isinstance(p, str) and p.strip(), f"{key}.path contains a missing/blank entry"
            # Every registered event's path must be unique -- two keys
            # (or two entries within the same event's own list)
            # accidentally pointing at the same file would silently make
            # one of them a duplicate rather than a distinct source.
            assert p not in seen_paths, f"{key}'s path {p!r} is already used by another event"
            seen_paths.add(p)
