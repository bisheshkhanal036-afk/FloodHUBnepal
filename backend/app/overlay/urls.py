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


def risk_surface_url(cache_key: str) -> str:
    return f"{ROUTER_PREFIX}/risk_surface/{cache_key}.tif"


def hazard_classes_url(cache_key: str) -> str:
    return f"{ROUTER_PREFIX}/hazard_classes/{cache_key}.tif"
