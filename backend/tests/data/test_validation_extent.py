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


def test_repeated_call_for_same_aoi_hits_the_processed_cache(test_aoi, monkeypatch, tmp_path):
    local_dir = _register_event(monkeypatch, tmp_path, "fake_event", "fake_event.shp")
    minx, miny, maxx, maxy = test_aoi.bbox_4326
    _write_fake_flood_extent_shp(local_dir / "fake_event.shp", [box(minx, miny, maxx, maxy)])

    first = get_observed_flood_mask(test_aoi, "fake_event")
    second = get_observed_flood_mask(test_aoi, "fake_event")

    assert np.array_equal(first.observed_flooded, second.observed_flooded)


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
