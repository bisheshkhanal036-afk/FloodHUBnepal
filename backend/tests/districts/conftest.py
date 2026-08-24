from __future__ import annotations

from pathlib import Path

import pytest

from app.data import config
from app.data.districts import reset_districts_cache

FIXTURE_PATH = Path(__file__).parent.parent / "data" / "fixtures" / "basins" / "test_districts.shp"


@pytest.fixture(autouse=True)
def use_districts_fixture(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_ADMIN_DISTRICTS_PATH", FIXTURE_PATH)
    reset_districts_cache()
    yield
    reset_districts_cache()
