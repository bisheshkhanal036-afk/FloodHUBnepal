"""REST endpoints for the overlay engine: computing a risk surface,
serving the resulting GeoTIFFs (continuous risk surface and discrete
hazard-class raster) back over HTTP, and the full vulnerability-
classification computation report.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.ahp.errors import AHPConsistencyError, AHPValidationError
from app.data import config
from app.data.errors import DataSourceUnavailableError, NodataValidationError, ReclassificationError
from app.data.validation_extent import get_validation_extent_geojson, list_validation_events

from .breaks import compute_criterion_breaks
from .errors import OverlayValidationError
from .hazard_classes import materialize_hazard_classes_from_risk_surface_tif
from .meteor_comparison import compare_risk_surface_to_meteor
from .meteor_tile_proxy import MeteorTileNotFoundError, fetch_meteor_flood_tile
from .models import (
    CompareMeteorRequest,
    CompareMeteorResponse,
    CriterionBreaksRequest,
    CriterionBreaksResponse,
    OverlayComputeRequest,
    OverlayComputeResponse,
    ValidateRequest,
    ValidateResponse,
    ValidationEventOut,
    VulnerabilityReportRequest,
    VulnerabilityReportResponse,
)
from .progress_stream import stream_compute_events
from .report import compute_vulnerability_report
from .service import compute_overlay
from .urls import (
    CRITERION_RASTER_PATH_PATTERN,
    HAZARD_CLASSES_PATH_PATTERN,
    METEOR_FLOOD_TILE_PATH_PATTERN,
    RISK_SURFACE_PATH_PATTERN,
    ROUTER_PREFIX,
    VALIDATION_EXTENT_GEOJSON_PATH_PATTERN,
)
from .validate import validate_risk_surface

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


@router.get("/validation-events", response_model=list[ValidationEventOut])
def validation_events() -> list[ValidationEventOut]:
    """Every registered real, satellite-observed flood event a risk
    surface can be validated against (config.VALIDATION_EVENTS) — for a
    caller (the frontend's own event selector) to list what's available
    without hardcoding event keys.
    """
    return [ValidationEventOut(key=key, label=label) for key, label in list_validation_events().items()]


@router.get(VALIDATION_EXTENT_GEOJSON_PATH_PATTERN)
def validation_extent_geojson(event: str) -> dict:
    """The named event's real flood-extent polygon as GeoJSON, ready for
    a MapLibre GeoJSON source -- the reference-overlay counterpart to
    POST /validate's own AUC number, the same "toggleable map layer"
    role MeteorFloodControl already fills for the (modeled) METEOR
    layer, placed in the same map control group by the frontend
    (MapView.jsx's own ValidationExtentControl). Simplified for display
    only (see get_validation_extent_geojson's own docstring) -- never
    used for the actual validation math, which reads the raw shapefile.

    Responds 404 for an unrecognized event (a plain 404, not the
    data_source_unavailable/503 the same "unrecognized" condition maps
    to elsewhere in this router — this route's own `event` is a path
    parameter naming a specific resource, so "doesn't exist" is exactly
    what a 404 means here); 503 if the event is registered but its local
    file is missing.
    """
    try:
        return get_validation_extent_geojson(event)
    except DataSourceUnavailableError as exc:
        if event not in config.VALIDATION_EVENTS:
            raise HTTPException(status_code=404, detail={"error": "validation_event_not_found", "message": str(exc)}) from exc
        raise HTTPException(status_code=503, detail={"error": "data_source_unavailable", "message": str(exc)}) from exc


@router.post("/validate", response_model=ValidateResponse)
def validate(payload: ValidateRequest) -> ValidateResponse:
    """Validates the same risk surface POST /compute would produce for
    this AOI/criteria/final_weights against a real satellite-observed
    flood extent (not another model's output — see app/data/
    validation_extent.py's own module docstring for why that distinction
    matters). Reuses POST /compute's own cache: an AOI/criteria/weights
    combination already computed via /compute is not recomputed here.

    Returns two families of metrics: threshold-free (success_rate.py's
    `auc`/`curve` and `pr_auc`/`precision_recall_curve`, swept over
    every possible cutoff of the continuous risk score) and threshold-
    based (confusion_metrics.py's `precision`/`recall`/`f1`/`iou`, all
    scored at the one already-meaningful High/Very-High hazard-class
    operating point this app uses everywhere else).

    Responds 422 if the criteria/weights are malformed (same as POST
    /compute), if `event` doesn't name a registered validation event, or
    if the AOI simply doesn't overlap that event's real flood extent at
    all (zero observed-flooded pixels in the valid risk-surface area —
    an expected "wrong AOI for this event" case, not a server error).
    Responds 503 if a contributing criterion's data source, or the
    validation event's own local file, is unavailable.
    """
    aoi = payload.aoi.to_domain()
    criteria = [c.to_domain() for c in payload.criteria]

    try:
        result = validate_risk_surface(aoi, criteria, payload.final_weights, payload.complete, payload.event)
    except OverlayValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": "overlay_validation_error", "message": str(exc)}) from exc
    except (NodataValidationError, ReclassificationError) as exc:
        raise HTTPException(status_code=422, detail={"error": "overlay_data_error", "message": str(exc)}) from exc
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "data_source_unavailable", "message": str(exc)}) from exc

    sr = result.success_rate
    cm = result.confusion_metrics
    return ValidateResponse(
        auc=sr.auc,
        curve=sr.curve,
        pr_auc=sr.pr_auc,
        precision_recall_curve=sr.precision_recall_curve,
        precision=cm.precision,
        recall=cm.recall,
        f1=cm.f1,
        iou=cm.iou,
        true_positive_pixels=cm.true_positive,
        false_positive_pixels=cm.false_positive,
        false_negative_pixels=cm.false_negative,
        true_negative_pixels=cm.true_negative,
        n_valid_pixels=sr.n_valid_pixels,
        n_observed_flooded_pixels=sr.n_observed_flooded_pixels,
        observed_flooded_fraction=sr.observed_flooded_fraction,
        risk_surface_cache_key=result.risk_surface_cache_key,
        event=result.event,
        event_label=result.event_label,
        attribution=result.attribution,
    )


@router.post("/compare-meteor", response_model=CompareMeteorResponse)
def compare_meteor(payload: CompareMeteorRequest) -> CompareMeteorResponse:
    """Compares the same risk surface POST /compute would produce for
    this AOI/criteria/final_weights against METEOR's own modeled flood
    hazard (app/data/meteor_flood.py) — a check on agreement between two
    models, NOT validation against real-world accuracy (that's POST
    /validate's own job; see app/overlay/meteor_comparison.py's module
    docstring for why the two are kept deliberately separate). Reuses
    POST /compute's own cache the same way POST /validate does.

    Same two metric families POST /validate returns (threshold-free
    auc/curve/pr_auc/precision_recall_curve, and threshold-based
    precision/recall/f1/iou at the High/Very-High hazard operating
    point) — scored against METEOR's own `depth_m > 0` flooded mask
    instead of a real observed extent, for whichever single
    flood_type/return_period this server has a local METEOR file
    downloaded for (`meteor_flood_type`/`meteor_return_period` in the
    response — not caller-selectable; see app/data/meteor_flood.py).

    Responds 422 if the criteria/weights are malformed (same as POST
    /compute), or if the AOI falls entirely outside METEOR's own modeled
    floodplain domain (zero METEOR-flooded pixels in the valid risk-
    surface area — an expected "wrong AOI for this terrain" case, not a
    server error). Responds 503 if a contributing criterion's data
    source, or METEOR's own local file, is unavailable.
    """
    aoi = payload.aoi.to_domain()
    criteria = [c.to_domain() for c in payload.criteria]

    try:
        result = compare_risk_surface_to_meteor(aoi, criteria, payload.final_weights, payload.complete)
    except OverlayValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": "overlay_validation_error", "message": str(exc)}) from exc
    except (NodataValidationError, ReclassificationError) as exc:
        raise HTTPException(status_code=422, detail={"error": "overlay_data_error", "message": str(exc)}) from exc
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "data_source_unavailable", "message": str(exc)}) from exc

    sr = result.success_rate
    cm = result.confusion_metrics
    return CompareMeteorResponse(
        auc=sr.auc,
        curve=sr.curve,
        pr_auc=sr.pr_auc,
        precision_recall_curve=sr.precision_recall_curve,
        precision=cm.precision,
        recall=cm.recall,
        f1=cm.f1,
        iou=cm.iou,
        true_positive_pixels=cm.true_positive,
        false_positive_pixels=cm.false_positive,
        false_negative_pixels=cm.false_negative,
        true_negative_pixels=cm.true_negative,
        n_valid_pixels=sr.n_valid_pixels,
        n_meteor_flooded_pixels=sr.n_observed_flooded_pixels,
        meteor_flooded_fraction=sr.observed_flooded_fraction,
        risk_surface_cache_key=result.risk_surface_cache_key,
        meteor_flood_type=result.meteor_flood_type,
        meteor_return_period=result.meteor_return_period,
        attribution=result.attribution,
    )


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


@router.get(METEOR_FLOOD_TILE_PATH_PATTERN)
def get_meteor_flood_tile(
    flood_type: str = PathParam(..., pattern=r"^(fd|fu|p)$"),
    return_period: int = PathParam(...),
    z: int = PathParam(...),
    x: int = PathParam(...),
    y: int = PathParam(...),
) -> Response:
    """Proxies one tile from METEOR's live WMTS flood-hazard service —
    see meteor_tile_proxy.py's own module docstring for why this exists
    at all: METEOR's tile server sends no CORS headers, so MapLibre GL
    (which needs `crossOrigin` to read tile pixels into a WebGL texture)
    can never load them directly from the browser. This backend has no
    such restriction (browsers, not servers, enforce CORS), so it fetches
    the real tile server-side and hands the bytes back from an origin
    the frontend already trusts.

    `flood_type`'s charset is pattern-constrained here too (defense in
    depth, same reasoning as CRITERION_RASTER_PATH_PATTERN's own
    `criterion_id` pattern); the real allow-list check (both
    flood_type and return_period, against METEOR's actual live catalog)
    happens inside fetch_meteor_flood_tile itself.

    Responds 422 for a flood_type/return_period outside METEOR's real
    catalog. Responds 404 for a z/x/y the upstream itself rejects as
    outside its own tile matrix — a normal, routine condition at the
    edges of a raster tile source's coverage/zoom range, not a service
    failure. Responds 503 only for a genuine upstream failure (network
    error, timeout, or a 5xx from METEOR's own server).
    """
    try:
        tile_bytes = fetch_meteor_flood_tile(flood_type, return_period, z, x, y)
    except OverlayValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": "overlay_validation_error", "message": str(exc)}) from exc
    except MeteorTileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"error": "meteor_tile_not_found", "message": str(exc)}) from exc
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "data_source_unavailable", "message": str(exc)}) from exc

    return Response(
        content=tile_bytes,
        media_type="image/png",
        # METEOR's own tiles are static (a fixed pre-run model output,
        # not live/time-varying data) -- safe for the browser to cache
        # aggressively rather than re-fetching on every pan/zoom.
        headers={"Cache-Control": "public, max-age=86400"},
    )


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
