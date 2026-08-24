"""Unit tests for the recent-rainfall criterion source.

Split the same way test_dem.py/test_osm.py are: pure logic (URL
construction, accumulation math, staleness accounting) tested in
isolation with no network I/O, and a handful of `slow`-marked tests that
hit the real CHIRPS server for occasional manual verification. Excluded
from the default run (pytest.ini: `addopts = -m "not slow"`).
"""

from __future__ import annotations

import datetime

import numpy as np
import pytest

from app.data.recent_rainfall import (
    CHIRPS_SOURCE_NODATA,
    RECENT_RAINFALL_OUTPUT_NODATA,
    _chirps_url,
    _find_latest_available_date,
)


# --- URL construction ---


def test_chirps_url_zero_pads_month_and_day():
    url = _chirps_url(datetime.date(2026, 3, 5))
    assert url.endswith("/2026/chirps-v3.0.prelim.2026.03.05.tif")


def test_chirps_url_uses_configured_base():
    from app.data import recent_rainfall

    url = _chirps_url(datetime.date(2026, 1, 1))
    assert url.startswith(recent_rainfall.CHIRPS_BASE_URL)


# --- _find_latest_available_date: probing logic, with a fake existence check ---


def test_finds_the_first_available_date_walking_backwards(monkeypatch):
    """Today's and yesterday's files aren't published yet; the day before
    is -- the probe must walk backwards and stop at the first hit, not
    the first miss.
    """
    from app.data import recent_rainfall

    available = {datetime.date(2026, 8, 20)}
    monkeypatch.setattr(recent_rainfall, "_daily_file_exists", lambda d: d in available)

    result = _find_latest_available_date(datetime.date(2026, 8, 24))
    assert result == datetime.date(2026, 8, 20)


def test_todays_file_is_used_if_it_happens_to_exist(monkeypatch):
    from app.data import recent_rainfall

    monkeypatch.setattr(recent_rainfall, "_daily_file_exists", lambda d: True)

    result = _find_latest_available_date(datetime.date(2026, 8, 24))
    assert result == datetime.date(2026, 8, 24)


def test_gives_up_after_max_lookback_with_an_explicit_error(monkeypatch):
    from app.data.errors import DataSourceUnavailableError
    from app.data import recent_rainfall

    monkeypatch.setattr(recent_rainfall, "_daily_file_exists", lambda d: False)

    with pytest.raises(DataSourceUnavailableError, match="no CHIRPS-prelim file found"):
        _find_latest_available_date(datetime.date(2026, 8, 24))


# --- accumulation logic: exercised directly against get_recent_rainfall's
# inner behaviour by monkeypatching the day-reader, so the maths is
# verified without any network I/O ---


def test_accumulation_sums_available_days_and_flags_missing_ones(monkeypatch):
    from app.data.aoi import AOI
    from app.data.grid import AOIGrid
    from app.data import recent_rainfall

    grid = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=2, height=2)
    monkeypatch.setattr(recent_rainfall, "compute_aoi_grid", lambda bounds: grid)
    monkeypatch.setattr(recent_rainfall, "_find_latest_available_date", lambda today: datetime.date(2026, 8, 20))

    # 7-day window; day 3 back (2026-08-17) is "missing" (raises), the
    # other 6 each contribute a flat 10mm everywhere.
    from rasterio.errors import RasterioIOError

    def fake_read(day, grid_):
        if day == datetime.date(2026, 8, 17):
            raise RasterioIOError("simulated gap in the record")
        return np.full((grid_.height, grid_.width), 10.0, dtype=np.float32)

    monkeypatch.setattr(recent_rainfall, "_read_day_on_grid", fake_read)
    monkeypatch.setattr(recent_rainfall, "cached_or_compute", lambda name, aoi, fn, version="": fn())

    aoi = AOI(bbox_4326=(85.0, 27.0, 85.1, 27.1))
    result = recent_rainfall.get_recent_rainfall(aoi, window_days=7)

    # 6 available days x 10mm = 60mm everywhere
    assert np.all(result.rainfall_mm == pytest.approx(60.0))
    assert "Only 6 of the requested 7 days" in result.warning


def test_a_cell_with_no_valid_day_anywhere_is_nodata(monkeypatch):
    from app.data.aoi import AOI
    from app.data.grid import AOIGrid
    from app.data import recent_rainfall

    grid = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=2, height=2)
    monkeypatch.setattr(recent_rainfall, "compute_aoi_grid", lambda bounds: grid)
    monkeypatch.setattr(recent_rainfall, "_find_latest_available_date", lambda today: datetime.date(2026, 8, 20))

    def fake_read(day, grid_):
        # Top-left cell is always nodata (e.g. a coastal/edge artifact);
        # every other cell always has data.
        arr = np.full((grid_.height, grid_.width), 5.0, dtype=np.float32)
        arr[0, 0] = RECENT_RAINFALL_OUTPUT_NODATA
        return arr

    monkeypatch.setattr(recent_rainfall, "_read_day_on_grid", fake_read)
    monkeypatch.setattr(recent_rainfall, "cached_or_compute", lambda name, aoi, fn, version="": fn())

    aoi = AOI(bbox_4326=(85.0, 27.0, 85.1, 27.1))
    result = recent_rainfall.get_recent_rainfall(aoi, window_days=3)

    assert result.rainfall_mm[0, 0] == RECENT_RAINFALL_OUTPUT_NODATA
    assert result.rainfall_mm[1, 1] == pytest.approx(15.0)  # 3 days x 5mm


def test_the_staleness_warning_always_states_this_is_not_a_live_reading(monkeypatch):
    """Non-negotiable: whatever the staleness turns out to be, the
    warning must never be silent about what this data is not.
    """
    from app.data.aoi import AOI
    from app.data.grid import AOIGrid
    from app.data import recent_rainfall

    grid = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=1, height=1)
    monkeypatch.setattr(recent_rainfall, "compute_aoi_grid", lambda bounds: grid)
    monkeypatch.setattr(recent_rainfall, "_find_latest_available_date", lambda today: today)
    monkeypatch.setattr(
        recent_rainfall,
        "_read_day_on_grid",
        lambda day, grid_: np.full((grid_.height, grid_.width), 1.0, dtype=np.float32),
    )
    monkeypatch.setattr(recent_rainfall, "cached_or_compute", lambda name, aoi, fn, version="": fn())

    aoi = AOI(bbox_4326=(85.0, 27.0, 85.1, 27.1))
    result = recent_rainfall.get_recent_rainfall(aoi, window_days=1)

    assert "not a live reading, forecast, or flood warning" in result.warning


def test_cache_version_changes_with_the_calendar_date():
    """The whole point of keying the cache by today's date: yesterday's
    accumulation must never be served for today's request.
    """
    calls = []

    def fake_cached_or_compute(name, aoi, fn, version=""):
        calls.append(version)
        return fn()

    import datetime as real_datetime
    from app.data.aoi import AOI
    from app.data.grid import AOIGrid
    from app.data import recent_rainfall
    import pytest as _pytest

    grid = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=1, height=1)

    with _pytest.MonkeyPatch.context() as m:
        m.setattr(recent_rainfall, "compute_aoi_grid", lambda bounds: grid)
        m.setattr(recent_rainfall, "_find_latest_available_date", lambda today: today)
        m.setattr(
            recent_rainfall,
            "_read_day_on_grid",
            lambda day, grid_: np.zeros((grid_.height, grid_.width), dtype=np.float32),
        )
        m.setattr(recent_rainfall, "cached_or_compute", fake_cached_or_compute)

        aoi = AOI(bbox_4326=(85.0, 27.0, 85.1, 27.1))
        recent_rainfall.get_recent_rainfall(aoi, window_days=1)

    assert len(calls) == 1
    assert real_datetime.date.today().isoformat() in calls[0]


# --- live network tests: real CHIRPS server, excluded by default (pytest.ini) ---


@pytest.mark.slow
def test_live_chirps_daily_file_opens_and_reports_expected_grid():
    import rasterio

    with rasterio.Env(GDAL_HTTP_TIMEOUT=30):
        with rasterio.open("/vsicurl/" + _chirps_url(datetime.date(2026, 8, 20))) as ds:
            assert ds.width == 7200
            assert ds.height == 2400
            assert str(ds.crs) == "EPSG:4326"


@pytest.mark.slow
def test_live_get_recent_rainfall_over_kathmandu_returns_plausible_values():
    from app.data.aoi import AOI
    from app.data.recent_rainfall import get_recent_rainfall

    aoi = AOI(bbox_4326=(85.30, 27.67, 85.38, 27.73))
    result = get_recent_rainfall(aoi)

    valid = result.rainfall_mm[result.rainfall_mm != RECENT_RAINFALL_OUTPUT_NODATA]
    assert valid.size > 0
    # A week's monsoon accumulation over Kathmandu Valley: plausible
    # bound, not a tight one -- this is a live smoke test, not a golden
    # value (the true value changes every day by design).
    assert 0.0 <= valid.mean() <= 500.0
    assert result.days_stale >= 0
    assert "not a live reading" in result.warning
