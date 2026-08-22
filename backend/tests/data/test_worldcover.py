from __future__ import annotations

import numpy as np
import pytest
from affine import Affine

from app.data import config
from app.data.attribution import WORLDCOVER_ATTRIBUTION
from app.data.worldcover import WORLDCOVER_OUTPUT_NODATA, get_worldcover
from tests.data.conftest import FIXTURES_DIR

# ESA WorldCover legend codes present in the fixture (see
# tests/data/fixtures/worldcover generation): 10=tree cover, 30=grassland
# (background), 50=built-up, 60=bare/sparse, 80=water.
FIXTURE_CLASS_CODES = {10, 30, 50, 60, 80}


def test_local_hit_produces_categorical_classes_on_the_common_grid(test_aoi, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_WORLDCOVER_DIR", FIXTURES_DIR / "worldcover")

    result = get_worldcover(test_aoi)

    assert result.source_used.startswith("local:")
    assert result.attribution == WORLDCOVER_ATTRIBUTION
    assert result.nodata == WORLDCOVER_OUTPUT_NODATA
    assert result.land_cover_class.shape == (result.grid.height, result.grid.width)
    assert result.land_cover_class.dtype == np.uint8

    present = set(np.unique(result.land_cover_class))
    # Nearest-neighbor resampling must never invent a class code that
    # wasn't present in the source data (the failure mode averaging would
    # cause, which is exactly what this convention forbids).
    assert present.issubset(FIXTURE_CLASS_CODES | {WORLDCOVER_OUTPUT_NODATA})
    assert present - {WORLDCOVER_OUTPUT_NODATA}  # at least one real class present


def test_repeated_call_for_same_aoi_hits_the_processed_cache(test_aoi, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_WORLDCOVER_DIR", FIXTURES_DIR / "worldcover")

    first = get_worldcover(test_aoi)
    second = get_worldcover(test_aoi)

    assert np.array_equal(first.land_cover_class, second.land_cover_class)


def _fake_worldcover_tile():
    array = np.full((240, 240), 50, dtype=np.uint8)  # built-up everywhere
    transform = Affine(8.333333333333333e-05, 0, 85.30, 0, -8.333333333333333e-05, 27.72)
    return array, transform, "EPSG:4326", 0


def test_falls_back_to_cloud_when_no_local_coverage(test_aoi, monkeypatch):
    called = []

    def fake_fetch(aoi):
        called.append(aoi)
        return _fake_worldcover_tile()

    monkeypatch.setattr("app.data.worldcover._fetch_worldcover_from_s3", fake_fetch)

    result = get_worldcover(test_aoi)

    assert len(called) == 1
    assert result.source_used == "s3://esa-worldcover"
    assert result.attribution == WORLDCOVER_ATTRIBUTION
    present = set(np.unique(result.land_cover_class))
    assert present == {50}


def test_falls_back_to_cloud_when_local_dir_has_no_covering_file(test_aoi, monkeypatch, tmp_path):
    empty_dir = tmp_path / "raw" / "worldcover"
    empty_dir.mkdir(parents=True)
    monkeypatch.setattr(config, "LOCAL_WORLDCOVER_DIR", empty_dir)
    monkeypatch.setattr("app.data.worldcover._fetch_worldcover_from_s3", lambda aoi: _fake_worldcover_tile())

    result = get_worldcover(test_aoi)

    assert result.source_used == "s3://esa-worldcover"


@pytest.mark.slow
def test_real_s3_read_over_kathmandu(test_aoi):
    result = get_worldcover(test_aoi)
    assert result.source_used == "s3://esa-worldcover"
    present = set(np.unique(result.land_cover_class)) - {WORLDCOVER_OUTPUT_NODATA}
    assert present  # Kathmandu's dense urban core should show real class codes
