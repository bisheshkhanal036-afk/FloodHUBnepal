"""Shared fixtures for the overlay engine test suite.

Deliberately self-contained rather than importing tests/data/conftest.py's
fixtures — Phase 1 and Phase 2 (including their test suites) are not to
be modified by this phase, so this duplicates the small amount of setup
(isolated cache dir, no-local-sources-by-default, the shared test AOI)
instead of reaching into tests/data/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.data import config
from app.data.aoi import AOI
from app.data.osm import reset_local_osm_parser_cache

# Same fixture files and AOI Phase 2's test suite uses (tests/data/fixtures/),
# referenced directly by path rather than by importing tests/data/conftest.py.
DATA_FIXTURES_DIR = Path(__file__).parent.parent / "data" / "fixtures"
TEST_AOI_BBOX_4326 = (85.3050, 27.7020, 85.3110, 27.7080)


@pytest.fixture
def test_aoi() -> AOI:
    return AOI(bbox_4326=TEST_AOI_BBOX_4326)


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROCESSED_CACHE_DIR", tmp_path / "cache" / "processed")


@pytest.fixture(autouse=True)
def no_local_sources_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_DEM_DIR", tmp_path / "raw" / "dem")
    monkeypatch.setattr(config, "LOCAL_WORLDCOVER_DIR", tmp_path / "raw" / "worldcover")
    monkeypatch.setattr(config, "LOCAL_OSM_DIR", tmp_path / "raw" / "osm")
    monkeypatch.setattr(config, "OSM_R2_BUILDINGS_URL", None)
    monkeypatch.setattr(config, "OSM_R2_ROADS_URL", None)
    monkeypatch.setattr(config, "OSM_R2_WATERWAYS_URL", None)
    reset_local_osm_parser_cache()
