from __future__ import annotations

from pathlib import Path

import pytest

from app.data import config
from app.data.basins import reset_basins_cache, reset_nepal_boundary_cache

FIXTURE_PATH = Path(__file__).parent.parent / "data" / "fixtures" / "basins" / "test_basins.shp"


@pytest.fixture(autouse=True)
def use_basin_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_BASINS_PATH", FIXTURE_PATH)
    # No Nepal boundary file by default -> these tests' expected
    # support_status/pct_in_nepal values are against the NEPAL_BBOX_4326
    # fallback proxy (the true-boundary path has its own dedicated test
    # in tests/data/test_basins.py).
    monkeypatch.setattr(config, "LOCAL_NEPAL_BOUNDARY_PATH", tmp_path / "no_such_file.shp")
    reset_basins_cache()
    reset_nepal_boundary_cache()
    yield
    reset_basins_cache()
    reset_nepal_boundary_cache()
