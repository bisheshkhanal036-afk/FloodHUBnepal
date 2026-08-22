"""REST endpoints for the overlay engine: computing a risk surface, and
serving the resulting GeoTIFF back over HTTP so the frontend can load it
directly as a raster/image source.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import FileResponse

from app.data import config
from app.data.errors import DataSourceUnavailableError, NodataValidationError, ReclassificationError

from .breaks import compute_criterion_breaks
from .errors import OverlayValidationError
from .models import (
    CriterionBreaksRequest,
    CriterionBreaksResponse,
    OverlayComputeRequest,
    OverlayComputeResponse,
)
from .service import compute_overlay
from .urls import RISK_SURFACE_PATH_PATTERN, ROUTER_PREFIX

router = APIRouter(prefix=ROUTER_PREFIX, tags=["overlay"])


@router.post("/compute", response_model=OverlayComputeResponse)
def compute(payload: OverlayComputeRequest) -> OverlayComputeResponse:
    """Compute (or fetch from cache) the composite risk surface for one
    AOI, given a criteria list (with reclassification_rules) and Phase
    1's AHP final_weights. Responds 422 if the AOI exceeds the area cap
    (schemas/aoi.schema.json), `complete` is False, the criteria/weights
    don't match, a criterion names an unrecognized source, or two
    criteria end up on mismatched grids. Responds 503 if a Phase 2 data
    source that isn't available (e.g. OSM with no local file and no R2
    configured) is needed — never silently substituted.
    """
    aoi = payload.aoi.to_domain()
    criteria = [c.to_domain() for c in payload.criteria]

    try:
        result = compute_overlay(aoi, criteria, payload.final_weights, payload.complete)
    except OverlayValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": "overlay_validation_error", "message": str(exc)}) from exc
    except (NodataValidationError, ReclassificationError) as exc:
        raise HTTPException(status_code=422, detail={"error": "overlay_data_error", "message": str(exc)}) from exc
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "data_source_unavailable", "message": str(exc)}) from exc

    return OverlayComputeResponse.from_overlay_result(result)


@router.post("/criteria/breaks", response_model=CriterionBreaksResponse)
def criteria_breaks(payload: CriterionBreaksRequest) -> CriterionBreaksResponse:
    """Candidate reclassification break points for one criterion source
    over one AOI — equal-interval, quantile, and Jenks natural breaks
    (4 interior breaks each, 5 classes), plus the raw value range, so a
    caller (the frontend's classification editor) can offer data-driven
    starting points for `reclassification_rules` instead of only this
    app's static defaults. Never triggers an overlay computation itself
    — same error handling as POST /compute (422 for an unrecognized
    source or an AOI with no valid pixels for it, 503 if the underlying
    data source is unavailable), since it resolves the raw layer through
    the exact same registry.
    """
    aoi = payload.aoi.to_domain()

    try:
        result = compute_criterion_breaks(aoi, payload.source)
    except OverlayValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": "overlay_validation_error", "message": str(exc)}) from exc
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "data_source_unavailable", "message": str(exc)}) from exc

    return CriterionBreaksResponse(**result)


@router.get(RISK_SURFACE_PATH_PATTERN)
def get_risk_surface_file(cache_key: str = PathParam(..., pattern=r"^[a-f0-9]{64}$")) -> FileResponse:
    """Serve a previously computed risk surface's GeoTIFF. `cache_key`
    comes from a prior POST /compute response — this route only ever
    reads an already-materialized file, it never triggers a computation.

    Reads config.PROCESSED_CACHE_DIR dynamically (not bound at import/
    mount time) specifically so this stays correct under DATA_DIR being
    reconfigured via environment variable, and so it's cleanly
    monkeypatchable in tests — the same reason every Phase 2 source
    module reads its own config values this way rather than importing
    them by value.
    """
    path = config.PROCESSED_CACHE_DIR / "risk_surface" / f"{cache_key}.tif"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "risk_surface_not_found",
                "message": f"no risk surface cached for cache_key={cache_key!r}; compute it first via POST {ROUTER_PREFIX}/compute",
            },
        )
    return FileResponse(path, media_type="image/tiff", filename=f"{cache_key}.tif")
