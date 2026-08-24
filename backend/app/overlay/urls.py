"""The URL shape for fetching a materialized risk-surface GeoTIFF —
defined once here so router.py's actual route and models.py's response
`data_url` construction can't drift apart. (Kept out of both router.py
and models.py to avoid a circular import between them.)
"""

from __future__ import annotations

ROUTER_PREFIX = "/api/overlay"

# A FastAPI/Starlette path pattern (the literal {cache_key} is a path
# parameter placeholder, not a Python format placeholder).
RISK_SURFACE_PATH_PATTERN = "/risk_surface/{cache_key}.tif"
HAZARD_CLASSES_PATH_PATTERN = "/hazard_classes/{cache_key}.tif"
CRITERION_RASTER_PATH_PATTERN = "/criterion_raster/{cache_key}/{criterion_id}.tif"

# meteor_tile_proxy.py's own tile-forwarding route -- {z}/{x}/{y} stay as
# literal placeholders in the frontend's own tile URL *template* (handed
# straight to MapLibre, which substitutes them itself, the same way it
# already does for every other raster source's `tiles` array in
# MapView.jsx's BASEMAPS), unlike flood_type/return_period, which the
# frontend always fills in concretely before building the template.
METEOR_FLOOD_TILE_PATH_PATTERN = "/meteor_flood_tile/{flood_type}/{return_period}/{z}/{x}/{y}.png"


def risk_surface_url(cache_key: str) -> str:
    return f"{ROUTER_PREFIX}/risk_surface/{cache_key}.tif"


def hazard_classes_url(cache_key: str) -> str:
    return f"{ROUTER_PREFIX}/hazard_classes/{cache_key}.tif"


def criterion_raster_url(cache_key: str, criterion_id: str) -> str:
    return f"{ROUTER_PREFIX}/criterion_raster/{cache_key}/{criterion_id}.tif"
