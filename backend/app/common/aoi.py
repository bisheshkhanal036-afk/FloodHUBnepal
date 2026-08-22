"""Shared AOI request input, with the area-cap enforced once here rather
than re-implemented per endpoint. Every endpoint that accepts an AOI in
its request body should use this `AOIInput` model for that field — the
cap check then applies automatically, the same way, everywhere, without
each route author having to remember to add it.

Per schemas/aoi.schema.json: `max_area_km2` defaults to 1000 km^2 for a
plain bbox-only AOI (raised from an initial 500 km^2 — real HydroBASINS
basins routinely exceed 500 km^2, which rejected legitimate basin
selections outright). A request whose bbox-only AOI exceeds the cap is
rejected with a clear 422, not silently clipped.

A basin selection (any AOI with `polygon` set) is EXEMPT from the cap
entirely, at the user's explicit request -- a hand-drawn rectangle can
be arbitrarily (and often accidentally) large, but a basin is a real,
fixed-size hydrological unit; capping it means some legitimate basins
could never be analyzed at all no matter how the cap is tuned. This does
carry a real cost/memory risk this module does not otherwise guard
against: a very large basin (Nepal has some in the multi-thousand-km^2
range) means a proportionally large 10m-resolution grid -- tens to
hundreds of millions of pixels -- for every criterion raster in the
request, which can be genuinely slow and memory-heavy. Accepted here as
a deliberate tradeoff, not an oversight; a future phase could reintroduce
a (much higher) sanity ceiling or a resolution back-off for very large
basins specifically, if that turns out to matter in practice.

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

MAX_AREA_KM2 = 1000.0


class AOIInput(BaseModel):
    bbox: list[float] = Field(..., min_length=4, max_length=4, description="[minx, miny, maxx, maxy] in EPSG:4326.")
    polygon: dict[str, Any] | None = Field(
        None,
        description=(
            "Optional GeoJSON Polygon/MultiPolygon geometry, EPSG:4326 (e.g. from a basin "
            "selection). Omit for a plain bbox-only AOI. An AOI with polygon set is exempt "
            "from the area cap (see this module's docstring)."
        ),
    )

    @model_validator(mode="after")
    def _check_area_cap(self) -> "AOIInput":
        # A basin selection (polygon set) is exempt from the cap
        # entirely -- see module docstring. Only a plain bbox-only AOI
        # (a hand-drawn rectangle) is checked.
        if self.polygon is not None:
            return self
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
