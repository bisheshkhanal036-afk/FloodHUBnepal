"""Shared fixtures for the geospatial data layer test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.data import config
from app.data.aoi import AOI
from app.data.osm import reset_local_osm_parser_cache

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# A small bbox around Kathmandu Durbar Square, comfortably inside the
# DEM/WorldCover fixture rasters' extent (85.30, 27.70, 85.32, 27.72) and
# containing the synthetic building/road in the OSM .pbf fixture.
TEST_AOI_BBOX_4326 = (85.3050, 27.7020, 85.3110, 27.7080)


@pytest.fixture
def test_aoi() -> AOI:
    return AOI(bbox_4326=TEST_AOI_BBOX_4326)


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path, monkeypatch):
    """Every test gets its own empty processed-cache directory, so cache
    hits/misses in one test can never leak into another, and tests never
    write into the real backend/data/cache/processed/.
    """
    monkeypatch.setattr(config, "PROCESSED_CACHE_DIR", tmp_path / "cache" / "processed")


@pytest.fixture(autouse=True)
def no_local_sources_by_default(tmp_path, monkeypatch):
    """Every test starts with local source directories pointed at empty
    tmp_path locations — the "no local files present" case is the
    default, matching a fresh deployment. Tests that want to exercise the
    local-hit path explicitly monkeypatch these to FIXTURES_DIR.
    """
    monkeypatch.setattr(config, "LOCAL_DEM_DIR", tmp_path / "raw" / "dem")
    monkeypatch.setattr(config, "LOCAL_WORLDCOVER_DIR", tmp_path / "raw" / "worldcover")
    monkeypatch.setattr(config, "LOCAL_OSM_DIR", tmp_path / "raw" / "osm")
    # LOCAL_OSM_PROCESSED_DIR is its own constant (computed once, from
    # the ORIGINAL LOCAL_OSM_DIR, at import time) -- monkeypatching
    # LOCAL_OSM_DIR above does NOT retroactively move it, so it needs
    # its own override here. Without this, every test in this suite
    # would see tier 1's real backend/data/raw/osm/processed/*.fgb (once
    # generated) instead of the empty-by-default tmp_path every other
    # local source gets, silently short-circuiting all the .pbf-fixture-
    # based local-hit/fallback tests below it.
    monkeypatch.setattr(config, "LOCAL_OSM_PROCESSED_DIR", tmp_path / "raw" / "osm" / "processed")
    monkeypatch.setattr(config, "OSM_R2_BUILDINGS_URL", None)
    monkeypatch.setattr(config, "OSM_R2_ROADS_URL", None)
    monkeypatch.setattr(config, "OSM_R2_WATERWAYS_URL", None)
    reset_local_osm_parser_cache()
