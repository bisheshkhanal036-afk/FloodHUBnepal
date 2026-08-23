"""Orchestration: resolves each requested criterion to its reclassified
raster (Phase 2), runs the weighted-sum overlay (compute.py), caches the
result per RiskSurface.cache_key, and materializes it as a GeoTIFF for
the API response's `data_url`.
"""

from __future__ import annotations

import logging
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
) -> OverlayResult:
    """The full request-to-response pipeline for POST /api/overlay/compute.

    Rejects up front (before fetching any data) if `complete` is False —
    an incomplete AHP weight set is Phase 1's concern to resolve, not
    something this module tries to work around. compute_risk_surface
    still independently re-checks the actual weight sum too, so a caller
    that bypasses this `complete` flag (e.g. calling compute_risk_surface
    directly) doesn't lose that protection.
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
        {"criterion_id": c.id, "weight": final_weights[c.id], "reclassification_rules": c.reclassification_rules}
        for c in criteria
    ]
    cache_key = compute_cache_key(aoi, criteria_set)

    def _compute() -> tuple[RiskSurfaceResult, list[str], list[SourceWarning]]:
        rasters: list[CriterionRaster] = []
        attributions: set[str] = set()
        source_warnings: list[SourceWarning] = []
        for criterion in criteria:
            reclassified, grid, attribution, warning = resolve_criterion_raster(
                aoi, criterion.id, criterion.source, criterion.reclassification_rules
            )
            rasters.append(CriterionRaster(criterion_id=criterion.id, reclassified=reclassified, grid=grid))
            attributions.add(attribution)
            if warning:
                source_warnings.append(SourceWarning(criterion_id=criterion.id, message=warning))

        risk_surface_result = compute_risk_surface(rasters, final_weights)
        # A basin selection's AOI carries its true polygon shape, not
        # just its bounding rectangle -- without this, the result always
        # fills the full rectangular grid regardless of what shape was
        # actually selected (see mask_risk_surface_to_polygon's own
        # docstring). A plain drawn-bbox AOI has no polygon, so this is a
        # no-op for that case, exactly as before.
        if aoi.polygon is not None:
            risk_surface_result = mask_risk_surface_to_polygon(risk_surface_result, aoi.polygon_utm)
        return risk_surface_result, sorted(attributions), source_warnings

    risk_surface_result, attribution, source_warnings = cached_or_compute(
        "risk_surface", aoi, _compute, version=cache_key
    )

    tif_path = _risk_surface_tif_path(cache_key)
    if not tif_path.exists():
        write_risk_surface_geotiff(tif_path, risk_surface_result.risk_surface, risk_surface_result.grid, risk_surface_result.nodata)

    return OverlayResult(
        cache_key=cache_key,
        risk_surface=risk_surface_result,
        data_url=str(tif_path),
        attribution=attribution,
        source_warnings=source_warnings,
    )
