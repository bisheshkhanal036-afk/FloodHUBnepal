"""Orchestration: resolves each requested criterion to its reclassified
raster (Phase 2), runs the weighted-sum overlay (compute.py), caches the
result per RiskSurface.cache_key, and materializes it as a GeoTIFF for
the API response's `data_url`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.data import config
from app.data.aoi import AOI
from app.data.cache import cached_or_compute

from .compute import CriterionRaster, RiskSurfaceResult, compute_cache_key, compute_risk_surface, mask_risk_surface_to_polygon
from .errors import OverlayValidationError
from .geotiff import write_risk_surface_geotiff
from .sources import resolve_criterion_raster

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OverlayCriterionRequest:
    id: str
    source: str
    reclassification_rules: list[dict]
    stream_threshold_cells: int | None = None


@dataclass(frozen=True)
class SourceWarning:
    """A source-level caveat about one criterion's result quality — e.g.
    hydrology.py's twi/drainage_density flagging reduced edge reliability
    on a plain bbox AOI (see app/overlay/sources.py's registry contract).
    Distinct from `OverlayResult.attribution`: attribution is always the
    plain, unmodified source citation; this is only ever present when a
    source's registry function actually returns a non-None warning.
    """

    criterion_id: str
    message: str


@dataclass(frozen=True)
class OverlayResult:
    cache_key: str
    risk_surface: RiskSurfaceResult
    data_url: str
    attribution: list[str]
    source_warnings: list[SourceWarning]
    # Each requested criterion's own already-reclassified raster (1-5,
    # RECLASSIFIED_NODATA=0), the same ones combine_risk_surface used to
    # build risk_surface above -- kept rather than discarded so
    # report.py can materialize per-criterion GeoTIFF snapshots without
    # re-resolving any criterion a second time. POST /compute's own
    # response (OverlayComputeResponse.from_overlay_result) deliberately
    # never reads this field -- see report.py's own docstring for why
    # per-criterion snapshots are gated behind POST /report specifically.
    criterion_rasters: list[CriterionRaster]


def _risk_surface_tif_path(cache_key: str) -> Path:
    # Read config.PROCESSED_CACHE_DIR dynamically at call time (not
    # imported by value) so tests can monkeypatch it, same as every
    # Phase 2 source module does for its own config lookups.
    return config.PROCESSED_CACHE_DIR / "risk_surface" / f"{cache_key}.tif"


def compute_overlay(
    aoi: AOI,
    criteria: list[OverlayCriterionRequest],
    final_weights: dict[str, float],
    complete: bool,
    on_progress: Callable[[str], None] | None = None,
) -> OverlayResult:
    """The full request-to-response pipeline for POST /api/overlay/compute.

    Rejects up front (before fetching any data) if `complete` is False —
    an incomplete AHP weight set is Phase 1's concern to resolve, not
    something this module tries to work around. compute_risk_surface
    still independently re-checks the actual weight sum too, so a caller
    that bypasses this `complete` flag (e.g. calling compute_risk_surface
    directly) doesn't lose that protection.

    `on_progress`, if given, is called synchronously with a short
    human-readable message at each meaningful step (before/after
    resolving each criterion, before combining, before masking, before
    writing the GeoTIFF) — purely additive, default None means exactly
    the same behavior as before this parameter existed (every existing
    caller, including report.py's own compute_overlay call, passes
    nothing and is unaffected). Exists for POST /api/overlay/compute/
    stream (router.py) to surface real progress to the frontend during
    this call — not a fabricated/animated progress bar, an actual
    callback fired from inside this exact function as it does the real
    work, since a plain request/response cycle has no other way to
    report incremental state mid-request. See progress_stream.py for how
    that callback gets bridged out to an SSE response (this function
    itself has and needs no knowledge of streaming/threading — it just
    calls a plain function).
    """
    if not complete:
        raise OverlayValidationError(
            "AHP weights are incomplete (complete=False); the overlay engine only accepts a "
            "complete, valid weight set from Phase 1 — see HierarchyResult.complete"
        )

    criterion_ids = {c.id for c in criteria}
    weight_ids = set(final_weights.keys())
    if criterion_ids != weight_ids:
        raise OverlayValidationError(
            f"criteria and final_weights must refer to exactly the same set of ids: "
            f"criteria={sorted(criterion_ids)}, weights={sorted(weight_ids)}"
        )

    criteria_set = [
        {
            "criterion_id": c.id,
            "weight": final_weights[c.id],
            "reclassification_rules": c.reclassification_rules,
            "stream_threshold_cells": c.stream_threshold_cells,
        }
        for c in criteria
    ]
    cache_key = compute_cache_key(aoi, criteria_set)

    def _notify(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    def _compute() -> tuple[RiskSurfaceResult, list[str], list[SourceWarning], list[CriterionRaster]]:
        rasters: list[CriterionRaster] = []
        attributions: set[str] = set()
        source_warnings: list[SourceWarning] = []
        for i, criterion in enumerate(criteria, start=1):
            _notify(f"Resolving {criterion.id} ({i}/{len(criteria)}, source: {criterion.source})…")
            reclassified, grid, attribution, warning = resolve_criterion_raster(
                aoi,
                criterion.id,
                criterion.source,
                criterion.reclassification_rules,
                stream_threshold_cells=criterion.stream_threshold_cells,
            )
            rasters.append(CriterionRaster(criterion_id=criterion.id, reclassified=reclassified, grid=grid))
            attributions.add(attribution)
            if warning:
                source_warnings.append(SourceWarning(criterion_id=criterion.id, message=warning))
            _notify(f"{criterion.id} resolved")

        _notify(f"Combining {len(criteria)} criteria into the risk surface…")
        risk_surface_result = compute_risk_surface(rasters, final_weights)
        # A basin selection's AOI carries its true polygon shape, not
        # just its bounding rectangle -- without this, the result always
        # fills the full rectangular grid regardless of what shape was
        # actually selected (see mask_risk_surface_to_polygon's own
        # docstring). A plain drawn-bbox AOI has no polygon, so this is a
        # no-op for that case, exactly as before.
        if aoi.polygon is not None:
            _notify("Masking to the basin's true shape…")
            risk_surface_result = mask_risk_surface_to_polygon(risk_surface_result, aoi.polygon_utm)
        # rasters returned unmasked (raw per-criterion grid) -- report.py
        # applies its own polygon masking when materializing a snapshot,
        # rather than baking that in here, since POST /compute itself
        # never reads criterion_rasters at all (see OverlayResult's own
        # docstring on the field).
        return risk_surface_result, sorted(attributions), source_warnings, rasters

    _notify("Checking cache…")
    risk_surface_result, attribution, source_warnings, criterion_rasters = cached_or_compute(
        "risk_surface", aoi, _compute, version=cache_key
    )

    tif_path = _risk_surface_tif_path(cache_key)
    if not tif_path.exists():
        _notify("Writing the GeoTIFF…")
        write_risk_surface_geotiff(tif_path, risk_surface_result.risk_surface, risk_surface_result.grid, risk_surface_result.nodata)

    _notify("Done.")
    return OverlayResult(
        cache_key=cache_key,
        risk_surface=risk_surface_result,
        data_url=str(tif_path),
        attribution=attribution,
        source_warnings=source_warnings,
        criterion_rasters=criterion_rasters,
    )
