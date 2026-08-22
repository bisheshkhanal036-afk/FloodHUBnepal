"""Tests for the shared AOI request model + area-cap validation
(app/common/aoi.py), used by every AOI-accepting endpoint."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.common.aoi import MAX_AREA_KM2, AOIInput


def test_accepts_a_kathmandu_valley_sized_bbox():
    aoi_input = AOIInput(bbox=[85.3050, 27.7020, 85.3110, 27.7080])  # well under the cap
    domain = aoi_input.to_domain()
    assert domain.area_km2 < MAX_AREA_KM2


def test_rejects_a_bbox_exceeding_the_area_cap():
    # ~0.5deg x 0.5deg near Kathmandu's latitude is roughly 2,500+ km^2.
    with pytest.raises(ValidationError, match="exceeds the 1000"):
        AOIInput(bbox=[85.0, 27.0, 85.5, 27.5])


def test_rejects_wrong_length_bbox():
    with pytest.raises(ValidationError):
        AOIInput(bbox=[85.0, 27.0, 85.5])


def test_polygon_is_optional_and_defaults_to_a_bbox_only_aoi():
    aoi_input = AOIInput(bbox=[85.3050, 27.7020, 85.3110, 27.7080])
    domain = aoi_input.to_domain()
    assert domain.polygon is None


def test_accepts_a_geojson_polygon_and_carries_it_into_the_domain_aoi():
    # A small (~27 km^2) square, comfortably under the area cap.
    geojson_polygon = {
        "type": "Polygon",
        "coordinates": [[[85.30, 27.70], [85.35, 27.70], [85.35, 27.75], [85.30, 27.75], [85.30, 27.70]]],
    }
    aoi_input = AOIInput(bbox=[85.30, 27.70, 85.35, 27.75], polygon=geojson_polygon)

    domain = aoi_input.to_domain()

    assert domain.polygon is not None
    assert domain.polygon.geom_type == "Polygon"
    assert domain.bbox_4326 == (85.30, 27.70, 85.35, 27.75)


def test_a_polygon_aoi_is_exempt_from_the_area_cap_even_when_its_own_bbox_is_over():
    # A tall, narrow rectangle whose full-rectangle area is over the cap
    # (confirmed below by rejecting the equivalent bbox-only AOI) -- the
    # bbox-only version must still be rejected exactly as before.
    bbox = [85.0, 27.0, 85.1, 28.4]  # ~0.1deg x 1.4deg near Kathmandu's latitude, ~1,500+ km^2

    with pytest.raises(ValidationError, match="exceeds the 1000"):
        AOIInput(bbox=bbox)

    geojson_triangle = {
        "type": "Polygon",
        "coordinates": [[[85.0, 27.0], [85.1, 27.0], [85.0, 28.4], [85.0, 27.0]]],
    }
    # Must NOT raise, even though this triangle's own true area (~770 km^2)
    # is itself comfortably under the cap -- see the next test for the
    # case that actually proves the exemption (a polygon whose TRUE area
    # exceeds the cap too).
    aoi_input = AOIInput(bbox=bbox, polygon=geojson_triangle)
    assert aoi_input.to_domain().area_km2 < MAX_AREA_KM2


def test_a_polygon_aoi_is_exempt_even_when_its_true_area_also_exceeds_the_cap():
    # A basin selection is exempt from the area cap entirely (at the
    # user's explicit request -- see app/common/aoi.py's module
    # docstring), not just "exempt because its true shape happens to be
    # smaller than its bbox". This square's true area (well over
    # 2,000 km^2) itself exceeds MAX_AREA_KM2, and it must still be
    # accepted precisely because polygon is set.
    bbox = [85.0, 27.0, 85.5, 27.5]  # ~2,500+ km^2, same bbox test_rejects_a_bbox_exceeding_the_area_cap uses
    geojson_square = {
        "type": "Polygon",
        "coordinates": [[[85.0, 27.0], [85.5, 27.0], [85.5, 27.5], [85.0, 27.5], [85.0, 27.0]]],
    }

    aoi_input = AOIInput(bbox=bbox, polygon=geojson_square)  # must not raise

    assert aoi_input.to_domain().area_km2 > MAX_AREA_KM2  # confirms this really would have been over the cap
