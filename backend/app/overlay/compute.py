"""The overlay engine's pure computational core: weighted-sum AHP overlay
of already-reclassified criterion rasters into a single continuous [0,1]
risk surface. No I/O, no caching, no network — everything here is a pure
function of its arguments, so it's testable with hand-crafted arrays
independent of Phase 1 (AHP) or Phase 2 (data layer).

    R = sum(weight_i * reclassified_class_i)   for each pixel, class_i in {1,2,3,4,5}
    R_norm = (R - 1) / (5 - 1)

R_norm uses a FIXED-RANGE linear transform, not min-max over the AOI's
observed values — see RISK_SURFACE_NODATA and compute_risk_surface below
for why, and SPEC.md's Risk Surface section for the documented
convention every later phase should read this from rather than
re-deriving it.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

import numpy as np

from app.data.aoi import AOI
from app.data.grid import AOIGrid
from app.data.nodata import assert_consistent_nodata
from app.data.reclassify import RECLASSIFIED_NODATA, rules_fingerprint

from .errors import OverlayValidationError

# Outside [0, 1] on purpose, so it can never be confused with a real,
# computed risk score (see SPEC.md, Risk Surface section).
RISK_SURFACE_NODATA = -9999.0

# R = sum(weight_i * class_i) is a convex combination of values in
# [RISK_CLASS_MIN, RISK_CLASS_MAX] (weights sum to 1), so R itself always
# lands in that same range for any complete, valid weight set.
RISK_CLASS_MIN = 1
RISK_CLASS_MAX = 5

_WEIGHT_SUM_TOLERANCE = 1e-6


@dataclass(frozen=True)
class CriterionRaster:
    """One criterion's already-reclassified raster (risk classes 1-5,
    RECLASSIFIED_NODATA=0), tagged with the AOIGrid it's actually on —
    not assumed to match any other criterion's grid without checking.
    """

    criterion_id: str
    reclassified: np.ndarray
    grid: AOIGrid


@dataclass(frozen=True)
class RiskSurfaceResult:
    risk_surface: np.ndarray  # float32, shape (grid.height, grid.width), values in [0,1] or RISK_SURFACE_NODATA
    grid: AOIGrid
    nodata: float


def compute_risk_surface(rasters: list[CriterionRaster], weights: dict[str, float]) -> RiskSurfaceResult:
    """Combine `rasters` into one weighted-sum risk surface.

    Validates, in order:
    1. criteria and weights refer to exactly the same set of criterion ids
       (a criterion with no weight, or a weight with no matching criterion,
       is a request-shape error, not something to guess around).
    2. weights sum to 1 within floating-point tolerance — this module
       never re-normalizes; an incomplete/invalid weight set is rejected,
       full stop (that's Phase 1's concern, not this module's to fix).
    3. every raster shares the exact same AOIGrid (crs, resolution,
       origin, dimensions) as every other — compared as AOIGrid equality,
       not just array .shape, since two grids can have matching
       dimensions while covering different ground.
    4. all rasters agree on what nodata means (reclassify.RECLASSIFIED_NODATA,
       always 0 by construction, but checked explicitly rather than assumed).

    A pixel that is nodata (== RECLASSIFIED_NODATA) in *any* contributing
    criterion is RISK_SURFACE_NODATA in the output, regardless of what the
    other criteria say at that pixel — never silently treated as
    zero-risk or dropped from the sum without a trace.
    """
    if not rasters:
        raise OverlayValidationError("no criteria rasters supplied")

    criterion_ids = {r.criterion_id for r in rasters}
    if len(criterion_ids) != len(rasters):
        raise OverlayValidationError("duplicate criterion_id among the supplied rasters")
    weight_ids = set(weights.keys())
    if criterion_ids != weight_ids:
        raise OverlayValidationError(
            f"criteria and weights must refer to exactly the same set of ids: "
            f"criteria={sorted(criterion_ids)}, weights={sorted(weight_ids)}"
        )

    total_weight = sum(weights.values())
    if not math.isclose(total_weight, 1.0, abs_tol=_WEIGHT_SUM_TOLERANCE):
        raise OverlayValidationError(
            f"weights must sum to 1 (got {total_weight}); the overlay engine never "
            "re-normalizes an incomplete or invalid weight set — see Phase 1's "
            "HierarchyResult.complete"
        )

    reference = rasters[0]
    for r in rasters[1:]:
        if r.grid != reference.grid:
            raise OverlayValidationError(
                f"grid mismatch between criteria {reference.criterion_id!r} and {r.criterion_id!r}: "
                f"{reference.grid!r} != {r.grid!r}. All criteria for one AOI must already be on the "
                "same AOIGrid before overlay — this module never reprojects/resamples."
            )

    assert_consistent_nodata({r.criterion_id: float(RECLASSIFIED_NODATA) for r in rasters})

    grid = reference.grid
    shape = (grid.height, grid.width)
    for r in rasters:
        if r.reclassified.shape != shape:
            raise OverlayValidationError(
                f"criterion {r.criterion_id!r} array shape {r.reclassified.shape} does not match "
                f"its own grid's (height, width) = {shape}"
            )

    accumulated = np.zeros(shape, dtype=np.float64)
    any_nodata = np.zeros(shape, dtype=bool)
    for r in rasters:
        weight = weights[r.criterion_id]
        is_nodata = r.reclassified == RECLASSIFIED_NODATA
        any_nodata |= is_nodata
        accumulated += weight * r.reclassified.astype(np.float64)

    normalized = (accumulated - RISK_CLASS_MIN) / (RISK_CLASS_MAX - RISK_CLASS_MIN)
    normalized = np.where(any_nodata, RISK_SURFACE_NODATA, normalized).astype(np.float32)

    return RiskSurfaceResult(risk_surface=normalized, grid=grid, nodata=RISK_SURFACE_NODATA)


def compute_cache_key(aoi: AOI, criteria_set: list[dict]) -> str:
    """SHA-256 hex digest of (AOI bbox + true polygon shape, when present
    + criteria_set), matching schemas/risk_surface.schema.json's
    `cache_key` description. `criteria_set` is
    [{"criterion_id": str, "weight": float, "reclassification_rules": list[dict],
    "stream_threshold_cells": int | None}, ...] ("stream_threshold_cells" is optional
    in the input dict -- read via `.get()` below, `None` when absent).

    Includes `aoi.polygon`'s WKT when set, not just `bbox_4326`: since
    compute_overlay now masks the final surface to the true polygon shape
    (mask_risk_surface_to_polygon below) for a basin-derived AOI, two
    requests that share a bbox but differ in polygon (e.g. a hand-drawn
    AOI vs. a basin selection whose envelope happens to match it) must
    never collide on the same cache entry — they'd produce genuinely
    different masked surfaces.

    Also includes each criterion's reclassification_rules — via
    reclassify.rules_fingerprint, the exact same stable/canonical hash
    apply_reclassification_cached already uses to version its own
    (lower-level, per-criterion) cache entry, reused here rather than
    re-implemented, so the two caches can never disagree about what
    counts as "the same rules." This was a real correctness bug, not a
    theoretical one, before this fix: two requests for the same AOI and
    the same criterion_id/weight but DIFFERENT reclassification_rules
    (e.g. the frontend's classification editor submitting custom breaks)
    hashed to the *same* cache_key, so cache.cached_or_compute's disk
    cache — and the persisted risk_surface .tif at
    _risk_surface_tif_path(cache_key) — would silently serve the first
    request's result for the second, computed under the wrong rules.
    Caught live: two manual test requests with different breakpoints for
    the same criterion produced an identical cache_key.

    Also includes `stream_threshold_cells` (`c.get(...)`, `None` for
    every criterion but `drainage_density`/`hand`, and for those two
    whenever the caller doesn't override it) — the exact same class of
    bug this function was already fixed for once: without this, two
    requests for the same AOI/criterion/weight/reclassification_rules
    but DIFFERENT stream thresholds would hash identically and silently
    serve each other's cached raster, even though `get_drainage_density`/
    `get_hand`'s own lower-level cache correctly distinguishes them (see
    hydrology.py) — the exact scenario that bit reclassification_rules
    before this same gap was closed for it.
    """
    normalized_criteria = sorted(
        (
            {
                "criterion_id": c["criterion_id"],
                "weight": round(float(c["weight"]), 10),
                "reclassification_rules_fingerprint": rules_fingerprint(c["reclassification_rules"]),
                "stream_threshold_cells": c.get("stream_threshold_cells"),
            }
            for c in criteria_set
        ),
        key=lambda c: c["criterion_id"],
    )
    payload = json.dumps(
        {
            "bbox_4326": [round(v, 8) for v in aoi.bbox_4326],
            "polygon_wkt": aoi.polygon.wkt if aoi.polygon is not None else None,
            "criteria_set": normalized_criteria,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mask_array_to_polygon(array: np.ndarray, grid: AOIGrid, nodata, polygon_utm) -> np.ndarray:
    """Sets every pixel whose cell center does not fall inside
    `polygon_utm` (already reprojected to `grid`'s CRS — see
    AOI.polygon_utm) to `nodata`, leaving everything inside untouched.
    The shared core `mask_risk_surface_to_polygon` (below, for the
    combined risk surface) and `report.py`'s per-criterion snapshot
    masking both use — extracted here so a basin AOI's individual
    criterion rasters can get the exact same true-shape treatment as the
    combined surface, without duplicating the rasterize call.

    `all_touched=False` (pixel center must fall inside the polygon):
    matches this codebase's own established convention for "is this grid
    cell inside this shape" (app/data/density_raster.py's coverage
    rasterization uses the same setting for the same reason), as opposed
    to the `all_touched=True` distance_raster.py uses for line-nearness,
    a different question entirely.
    """
    from rasterio.features import rasterize

    inside_mask = rasterize(
        [(polygon_utm, 1)],
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        fill=0,
        all_touched=False,
        dtype=np.uint8,
    ).astype(bool)

    return np.where(inside_mask, array, array.dtype.type(nodata))


def mask_risk_surface_to_polygon(result: RiskSurfaceResult, polygon_utm) -> RiskSurfaceResult:
    """Sets every pixel of `result.risk_surface` whose cell does not fall
    inside `polygon_utm` to RISK_SURFACE_NODATA, leaving everything
    inside untouched — see _mask_array_to_polygon for the shared masking
    logic itself.

    Why: without this, a basin selection's risk surface always fills the
    AOI's full rectangular bounding envelope — every earlier stage
    (Phase 2 sources, compute_risk_surface above) works on that
    rectangular grid regardless of whether the AOI has a true `polygon`,
    since a raster grid is inherently rectangular. The frontend already
    renders RISK_SURFACE_NODATA pixels as fully transparent
    (MapView.jsx), so masking here is what actually makes a basin
    selection's *result* follow the basin's real shape on the map,
    rather than always looking like a rectangle regardless of what was
    selected.
    """
    masked = _mask_array_to_polygon(result.risk_surface, result.grid, result.nodata, polygon_utm)
    return RiskSurfaceResult(risk_surface=masked, grid=result.grid, nodata=result.nodata)
