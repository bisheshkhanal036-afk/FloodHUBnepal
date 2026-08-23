"""REST endpoints for the overlay engine: computing a risk surface,
serving the resulting GeoTIFFs (continuous risk surface and discrete
hazard-class raster) back over HTTP, and the full vulnerability-
classification computation report.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, StreamingResponse

from app.ahp.errors import AHPConsistencyError, AHPValidationError
from app.data import config
from app.data.errors import DataSourceUnavailableError, NodataValidationError, ReclassificationError

from .breaks import compute_criterion_breaks
from .errors import OverlayValidationError
from .hazard_classes import materialize_hazard_classes_from_risk_surface_tif
from .models import (
    CriterionBreaksRequest,
    CriterionBreaksResponse,
    OverlayComputeRequest,
    OverlayComputeResponse,
    VulnerabilityReportRequest,
    VulnerabilityReportResponse,
)
from .progress_stream import stream_compute_events
from .report import compute_vulnerability_report
from .service import compute_overlay
from .urls import (
    CRITERION_RASTER_PATH_PATTERN,
    HAZARD_CLASSES_PATH_PATTERN,
    RISK_SURFACE_PATH_PATTERN,
    ROUTER_PREFIX,
)

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


@router.post("/compute/stream")
def compute_stream(payload: OverlayComputeRequest) -> StreamingResponse:
    """Same computation as POST /compute, but as Server-Sent Events: zero
    or more `{"type": "progress", "message": str}` lines emitted as
    compute_overlay actually does the work (real progress — see
    progress_stream.py's own docstring for why this needs a background
    thread, not a fabricated/animated progress indicator), followed by
    exactly one terminal event: `{"type": "done", "result": ...}` (the
    same shape POST /compute's own JSON body has) on success, or
    `{"type": "error", "error": str, "message": str}` on failure.

    Deliberately a SEPARATE endpoint from POST /compute, not a
    behavior change to it: an SSE response's HTTP status is always 200
    (streaming has already started by the time an error is known), so a
    caller that wants real 4xx/5xx status codes — any non-interactive
    API caller, and report.py's own internal reuse of compute_overlay —
    keeps using POST /compute exactly as before. This route exists for
    the frontend's own interactive "Compute risk map" button, where
    seeing progress matters more than a status-code-driven contract.
    """
    aoi = payload.aoi.to_domain()
    criteria = [c.to_domain() for c in payload.criteria]
    return StreamingResponse(
        stream_compute_events(aoi, criteria, payload.final_weights, payload.complete),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        result = compute_criterion_breaks(aoi, payload.source, payload.stream_threshold_cells)
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


@router.get(HAZARD_CLASSES_PATH_PATTERN)
def get_hazard_classes_file(cache_key: str = PathParam(..., pattern=r"^[a-f0-9]{64}$")) -> FileResponse:
    """Serve the discrete 1-5 hazard-class raster (integer GIS classes,
    not the continuous [0,1] risk_surface) for a previously computed
    result — often what a user actually wants for GIS use. Derived and
    materialized lazily on first request straight from the already-
    materialized risk_surface .tif for this cache_key (no AOI needed, no
    recompute of the risk surface itself — see hazard_classes.
    materialize_hazard_classes_from_risk_surface_tif's own docstring),
    then served directly like GET /risk_surface/{cache_key}.tif on every
    later request. 404s with the same "compute it first" guidance if no
    risk_surface exists yet for this cache_key — this route can never
    itself trigger the underlying overlay computation.
    """
    hazard_path = config.PROCESSED_CACHE_DIR / "hazard_classes" / f"{cache_key}.tif"
    if not hazard_path.exists():
        risk_surface_path = config.PROCESSED_CACHE_DIR / "risk_surface" / f"{cache_key}.tif"
        if not risk_surface_path.exists():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "risk_surface_not_found",
                    "message": (
                        f"no risk surface cached for cache_key={cache_key!r}; compute it first via "
                        f"POST {ROUTER_PREFIX}/compute"
                    ),
                },
            )
        materialize_hazard_classes_from_risk_surface_tif(risk_surface_path, hazard_path)

    return FileResponse(hazard_path, media_type="image/tiff", filename=f"{cache_key}_hazard_classes.tif")


@router.get(CRITERION_RASTER_PATH_PATTERN)
def get_criterion_raster_file(
    cache_key: str = PathParam(..., pattern=r"^[a-f0-9]{64}$"),
    criterion_id: str = PathParam(..., pattern=r"^[A-Za-z0-9_-]+$"),
) -> FileResponse:
    """Serve one criterion's own already-reclassified raster (1-5 GIS
    classes, same convention as GET /hazard_classes/{cache_key}.tif) as a
    standalone GeoTIFF.

    Deliberately never triggers materialization itself, unlike GET
    /hazard_classes — this route only ever reads a file that POST
    /report already wrote as a side effect of generating a report for
    this cache_key (see report._materialize_criterion_rasters). That's
    what actually enforces "snapshots only after the report": a
    cache_key with a computed risk surface but no report yet still 404s
    here, by design, not merely because nothing happened to call this
    route yet.

    `criterion_id`'s pattern constraint mirrors OverlayCriterionInput's
    own (models.py) as defense in depth against path traversal, even
    though the write side already only ever accepts that same charset.
    """
    path = config.PROCESSED_CACHE_DIR / "criterion_rasters" / f"{cache_key}_{criterion_id}.tif"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "criterion_raster_not_found",
                "message": (
                    f"no criterion raster cached for cache_key={cache_key!r}, criterion_id={criterion_id!r}; "
                    f"generate the vulnerability report first via POST {ROUTER_PREFIX}/report"
                ),
            },
        )
    return FileResponse(path, media_type="image/tiff", filename=f"{cache_key}_{criterion_id}.tif")


@router.post("/report", response_model=VulnerabilityReportResponse)
def report(payload: VulnerabilityReportRequest) -> VulnerabilityReportResponse:
    """The full vulnerability-classification / computation report: hazard-
    class-tagged buildings, per-class area/population/building zonal
    statistics, and the AOI/criteria/weighting context that produced the
    result. Heavier than POST /compute (a building spatial join + zonal
    stats on top of it) — a separate endpoint rather than folded into
    POST /compute's own response, since a caller who only wants the risk
    surface itself shouldn't pay for this every time.

    Internally reuses POST /compute's own cache untouched: submitting
    the same aoi/criteria/final_weights/complete this endpoint already
    accepts to POST /compute first, then calling this endpoint with the
    identical values, hits that cache rather than recomputing the risk
    surface — see report.compute_vulnerability_report's own docstring
    for why this is a POST with a full request body rather than a bare
    GET by cache_key: the weighting section (AHP pairwise matrices,
    consistency ratios) isn't derivable from cache_key alone, since the
    base overlay engine never sees AHP-level detail, only the final flat
    weights.
    """
    aoi = payload.aoi.to_domain()
    criteria = [c.to_domain() for c in payload.criteria]
    criterion_names = {c.id: c.name for c in payload.criteria if c.name is not None}

    ahp_cluster_comparison = None
    ahp_within_cluster_comparisons = None
    if payload.weighting.method == "ahp":
        ahp_cluster_comparison = payload.weighting.cluster_comparison.model_dump()
        ahp_within_cluster_comparisons = {
            name: m.model_dump() for name, m in (payload.weighting.within_cluster_comparisons or {}).items()
        }

    try:
        result = compute_vulnerability_report(
            aoi,
            criteria,
            payload.final_weights,
            payload.complete,
            criterion_names=criterion_names,
            weighting_method=payload.weighting.method,
            ahp_cluster_comparison=ahp_cluster_comparison,
            ahp_within_cluster_comparisons=ahp_within_cluster_comparisons,
            hybas_id=payload.hybas_id,
            support_status=payload.support_status,
        )
    except OverlayValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": "overlay_validation_error", "message": str(exc)}) from exc
    except (NodataValidationError, ReclassificationError) as exc:
        raise HTTPException(status_code=422, detail={"error": "overlay_data_error", "message": str(exc)}) from exc
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "data_source_unavailable", "message": str(exc)}) from exc
    except AHPConsistencyError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc
    except AHPValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": "ahp_validation_error", "message": str(exc)}) from exc

    return VulnerabilityReportResponse.from_report(result)
