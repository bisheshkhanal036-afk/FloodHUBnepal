"""Shared AOI request input, with the area-cap enforced once here rather
than re-implemented per endpoint. Every endpoint that accepts an AOI in
its request body should use this `AOIInput` model for that field — the
cap check then applies automatically, the same way, everywhere, without
each route author having to remember to add it.

Per schemas/aoi.schema.json: `max_area_km2` defaults to 500 km^2 ("enough
to cover the Kathmandu Valley with headroom, while bounding per-request
compute cost"). A request whose AOI exceeds the cap is rejected with a
clear 422, not silently clipped.

`polygon` is optional and additive: omitting it (the original shape of
this model) gives a plain bbox-only AOI exactly as before. Passing a
GeoJSON polygon/multipolygon — e.g. copied straight from
GET /api/basins/{hybas_id}/aoi's response — carries the true shape
through into the domain AOI too (see app/data/aoi.py), so a basin
selection round-trips into POST /api/overlay/compute unchanged.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator
from shapely.geometry import shape

from app.data.aoi import AOI

MAX_AREA_KM2 = 500.0


class AOIInput(BaseModel):
    bbox: list[float] = Field(..., min_length=4, max_length=4, description="[minx, miny, maxx, maxy] in EPSG:4326.")
    polygon: dict[str, Any] | None = Field(
        None,
        description=(
            "Optional GeoJSON Polygon/MultiPolygon geometry, EPSG:4326 (e.g. from a basin "
            "selection). Omit for a plain bbox-only AOI."
        ),
    )

    @model_validator(mode="after")
    def _check_area_cap(self) -> "AOIInput":
        area_km2 = self.to_domain().area_km2
        if area_km2 > MAX_AREA_KM2:
            raise ValueError(
                f"AOI area {area_km2:.1f} km² exceeds the {MAX_AREA_KM2:.0f} km² cap "
                "(schemas/aoi.schema.json, max_area_km2); request a smaller bbox"
            )
        return self

    def to_domain(self) -> AOI:
        polygon_geom = shape(self.polygon) if self.polygon is not None else None
        return AOI(bbox_4326=tuple(self.bbox), polygon=polygon_geom)
