from __future__ import annotations

import pytest

from app.data.aoi import AOI


def test_bounds_utm_reprojects_into_utm_45n(test_aoi):
    minx, miny, maxx, maxy = test_aoi.bounds_utm
    # Kathmandu Valley sits comfortably inside UTM zone 45N; easting should
    # be in the few-hundred-thousand-meter range, not degrees.
    assert 1_00_000 < minx < 9_00_000
    assert 1_00_000 < maxx < 9_00_000
    assert minx < maxx
    assert miny < maxy


def test_area_km2_is_small_and_positive(test_aoi):
    # ~600m x 600m box -> well under 1 km^2, comfortably under the 500 km^2 cap.
    assert 0 < test_aoi.area_km2 < 1.0


def test_cache_key_is_deterministic():
    aoi_a = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72))
    aoi_b = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72))
    assert aoi_a.cache_key() == aoi_b.cache_key()


def test_cache_key_differs_for_different_bbox():
    aoi_a = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72))
    aoi_b = AOI(bbox_4326=(85.31, 27.70, 85.32, 27.72))
    assert aoi_a.cache_key() != aoi_b.cache_key()


@pytest.mark.parametrize("noise", [1e-10, -1e-10])
def test_cache_key_is_stable_under_float_noise_within_precision(noise):
    aoi_a = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72))
    aoi_b = AOI(bbox_4326=(85.30 + noise, 27.70, 85.32, 27.72))
    assert aoi_a.cache_key() == aoi_b.cache_key()
