from __future__ import annotations

import pytest
from shapely.geometry import box

from app.data.aoi import AOI


def test_polygon_utm_is_none_when_no_polygon_is_set(test_aoi):
    assert test_aoi.polygon is None
    assert test_aoi.polygon_utm is None


def test_polygon_utm_reprojects_the_polygon_into_utm_45n():
    polygon = box(85.30, 27.70, 85.32, 27.72)
    aoi = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72), polygon=polygon)

    polygon_utm = aoi.polygon_utm

    # Same UTM-zone sanity check as bounds_utm's own test, plus: the
    # reprojected polygon's own bounds must match bounds_utm exactly,
    # since both start from the same underlying bbox here.
    minx, miny, maxx, maxy = polygon_utm.bounds
    assert 1_00_000 < minx < 9_00_000
    assert 1_00_000 < maxx < 9_00_000
    assert (minx, miny, maxx, maxy) == pytest.approx(aoi.bounds_utm)


def test_bounds_utm_reprojects_into_utm_45n(test_aoi):
    minx, miny, maxx, maxy = test_aoi.bounds_utm
    # Kathmandu Valley sits comfortably inside UTM zone 45N; easting should
    # be in the few-hundred-thousand-meter range, not degrees.
    assert 1_00_000 < minx < 9_00_000
    assert 1_00_000 < maxx < 9_00_000
    assert minx < maxx
    assert miny < maxy


def test_area_km2_is_small_and_positive(test_aoi):
    # ~600m x 600m box -> well under 1 km^2, comfortably under the 1000 km^2 cap.
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
