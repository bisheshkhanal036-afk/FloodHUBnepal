"""AOI (Area of Interest) helpers shared by every source in this data
layer: EPSG:4326 <-> EPSG:32645 reprojection and the per-AOI cache key.
Mirrors schemas/aoi.schema.json's `bbox`/`crs` fields.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from pyproj import Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

WGS84 = "EPSG:4326"
UTM_45N = "EPSG:32645"  # SPEC.md, CRS convention: all metric calculations use this.

_TO_UTM = Transformer.from_crs(WGS84, UTM_45N, always_xy=True)


@dataclass(frozen=True)
class AOI:
    """bbox_4326 is (minx, miny, maxx, maxy) in EPSG:4326 degrees, matching
    schemas/aoi.schema.json.

    `polygon` is optional: None for a plain user-drawn bbox (the original,
    still-default shape of an AOI — every existing consumer of
    bbox_4326/bounds_utm keeps working completely unchanged for this
    case), or a true EPSG:4326 Polygon/MultiPolygon when the AOI came
    from something with real shape, like a selected basin
    (basins.basin_to_aoi) — in which case bbox_4326 is that geometry's
    bounding envelope, derived automatically, and consumers that don't
    care about true-shape correctness (DEM/WorldCover fetch, the overlay
    engine, all of it today) can simply ignore `polygon` and keep working
    against bbox_4326/bounds_utm exactly as before. A future consumer
    that needs true-shape correctness (e.g. flow accumulation for
    TWI/drainage density) can check `if aoi.polygon is not None` and clip
    to it instead.
    """

    bbox_4326: tuple[float, float, float, float]
    polygon: BaseGeometry | None = None

    @property
    def bounds_utm(self) -> tuple[float, float, float, float]:
        """The AOI's bounding envelope in EPSG:32645, used for every area/
        distance/grid calculation (SPEC.md, CRS convention). Reprojects
        all 4 corners rather than just (minx,miny)/(maxx,maxy): UTM's
        meridian convergence can rotate a WGS84-aligned rectangle
        slightly, so the true envelope isn't always just the two
        reprojected diagonal corners.

        Always derived from bbox_4326 alone, regardless of whether
        `polygon` is set — this is what makes every existing bbox-based
        consumer's behavior identical for a basin-derived AOI as for a
        hand-drawn one.
        """
        minx, miny, maxx, maxy = self.bbox_4326
        corners = [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]
        xs, ys = zip(*(_TO_UTM.transform(x, y) for x, y in corners))
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def area_km2(self) -> float:
        """The bbox rectangle's area in km², UNLESS a true `polygon` is
        set, in which case this is the polygon's own true area (also
        reprojected to EPSG:32645, never computed directly in degrees —
        SPEC.md, CRS convention) — a basin's real shape is very often
        much smaller than its bounding rectangle, and using the true area
        here (for the area-cap check in particular) avoids rejecting a
        legitimately modest-sized, oddly-shaped basin just because its
        envelope is large.
        """
        if self.polygon is not None:
            return shapely_transform(_TO_UTM.transform, self.polygon).area / 1_000_000.0
        minx, miny, maxx, maxy = self.bounds_utm
        return ((maxx - minx) * (maxy - miny)) / 1_000_000.0

    def cache_key(self) -> str:
        """Stable per-AOI hash used to key the processed-raster cache
        (cache.py) — deliberately independent of AHP criteria/weights,
        unlike RiskSurface.cache_key in schemas/risk_surface.schema.json,
        since a raw processed DEM/WorldCover/OSM clip doesn't depend on
        either.

        Deliberately independent of `polygon` too: every current consumer
        (DEM/WorldCover/OSM fetch) only ever reads bbox_4326, so two AOIs
        that share a bbox_4326 but differ in `polygon` would fetch and
        produce byte-identical results today — keying the cache on
        bbox_4326 alone is therefore correct, not an oversight. This
        would need revisiting only once some consumer actually starts
        using `polygon` to clip to the true shape.
        """
        payload = json.dumps({"bbox_4326": [round(v, 8) for v in self.bbox_4326]}, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
