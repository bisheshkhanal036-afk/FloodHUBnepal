"""The shared local-check-first helper (used identically by DEM and
WorldCover) — existence check + AOI coverage check.
"""

from __future__ import annotations

from app.data.aoi import AOI
from app.data.local_source import find_local_raster_covering_aoi
from tests.data.conftest import FIXTURES_DIR, TEST_AOI_BBOX_4326


def test_returns_none_when_directory_does_not_exist(tmp_path):
    aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326)
    match = find_local_raster_covering_aoi(tmp_path / "does_not_exist", aoi)
    assert match is None


def test_returns_none_when_directory_is_empty(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326)
    match = find_local_raster_covering_aoi(empty_dir, aoi)
    assert match is None


def test_finds_dem_fixture_that_covers_the_test_aoi():
    aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326)
    match = find_local_raster_covering_aoi(FIXTURES_DIR / "dem", aoi)
    assert match is not None
    assert match.path.name == "test_aoi_dem.tif"


def test_finds_worldcover_fixture_that_covers_the_test_aoi():
    aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326)
    match = find_local_raster_covering_aoi(FIXTURES_DIR / "worldcover", aoi)
    assert match is not None
    assert match.path.name == "test_aoi_worldcover.tif"


def test_returns_none_when_local_file_does_not_cover_the_aoi():
    # An AOI far outside Kathmandu Valley (and outside the fixture's extent).
    far_away_aoi = AOI(bbox_4326=(0.0, 0.0, 0.02, 0.02))
    match = find_local_raster_covering_aoi(FIXTURES_DIR / "dem", far_away_aoi)
    assert match is None
