"""Overlay engine: combines Phase 1 (AHP final_weights) and Phase 2
(reclassified criterion rasters) into a single continuous [0,1] risk
surface. See compute.py for the pure weighted-sum math and its
citations/conventions, service.py for the caching/orchestration
pipeline, and router.py for the POST /api/overlay/compute endpoint.
"""

from .compute import (
    RISK_CLASS_MAX,
    RISK_CLASS_MIN,
    RISK_SURFACE_NODATA,
    CriterionRaster,
    RiskSurfaceResult,
    compute_cache_key,
    compute_risk_surface,
)
from .errors import OverlayValidationError
from .router import router
from .service import OverlayCriterionRequest, OverlayResult, compute_overlay

__all__ = [
    "RISK_SURFACE_NODATA",
    "RISK_CLASS_MIN",
    "RISK_CLASS_MAX",
    "CriterionRaster",
    "RiskSurfaceResult",
    "compute_risk_surface",
    "compute_cache_key",
    "OverlayValidationError",
    "OverlayCriterionRequest",
    "OverlayResult",
    "compute_overlay",
    "router",
]
