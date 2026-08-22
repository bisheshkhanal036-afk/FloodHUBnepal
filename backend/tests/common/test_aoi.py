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
    with pytest.raises(ValidationError, match="exceeds the 500"):
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


def test_area_cap_uses_true_polygon_area_not_bbox_envelope_area():
    # A tall, narrow rectangle whose full-rectangle area is over the cap
    # (confirmed below by rejecting the equivalent bbox-only AOI), but
    # whose diagonal-half TRIANGLE is under the cap -- a right triangle
    # inscribed in a rectangle has exactly half the rectangle's area.
    bbox = [85.0, 27.0, 85.1, 27.7]

    with pytest.raises(ValidationError, match="exceeds the 500"):
        AOIInput(bbox=bbox)  # confirms the full rectangle really is over the cap

    geojson_triangle = {
        "type": "Polygon",
        "coordinates": [[[85.0, 27.0], [85.1, 27.0], [85.0, 27.7], [85.0, 27.0]]],
    }
    # Must NOT raise: the true triangle area is about half the rectangle's,
    # and comfortably under the cap even though its own bbox is not.
    aoi_input = AOIInput(bbox=bbox, polygon=geojson_triangle)
    assert aoi_input.to_domain().area_km2 < MAX_AREA_KM2
