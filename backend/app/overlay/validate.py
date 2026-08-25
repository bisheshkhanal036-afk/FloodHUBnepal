"""Orchestration for POST /api/overlay/validate: computes the same risk
surface POST /api/overlay/compute would (reusing compute_overlay
directly, so this benefits from its own cache too — validating the same
AOI/criteria/weights twice never recomputes the risk surface itself),
rasterizes a real, satellite-observed flood extent onto that exact same
grid, and scores the two against each other via a success-rate curve.

Deliberately a thin orchestration layer, not new modeling logic:
compute_overlay (service.py), get_observed_flood_mask
(app/data/validation_extent.py), and compute_success_rate_curve
(success_rate.py) each already do their own real work; this module only
wires them together and shapes the result for the API response.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.data.aoi import AOI
from app.data.validation_extent import get_observed_flood_mask

from .confusion_metrics import ConfusionMetricsResult, compute_confusion_metrics
from .hazard_classes import HAZARD_CLASS_NODATA, risk_surface_to_hazard_classes
from .service import OverlayCriterionRequest, compute_overlay
from .success_rate import SuccessRateResult, compute_success_rate_curve


@dataclass(frozen=True)
class ValidationResult:
    success_rate: SuccessRateResult
    confusion_metrics: ConfusionMetricsResult
    risk_surface_cache_key: str
    event: str
    event_label: str
    attribution: list[str]


def validate_risk_surface(
    aoi: AOI,
    criteria: list[OverlayCriterionRequest],
    final_weights: dict[str, float],
    complete: bool,
    event: str,
) -> ValidationResult:
    """Raises the same exceptions compute_overlay itself can (
    OverlayValidationError, NodataValidationError, ReclassificationError,
    DataSourceUnavailableError) for anything that goes wrong producing
    the risk surface; DataSourceUnavailableError if `event` isn't
    registered or its local file is missing (get_observed_flood_mask);
    OverlayValidationError if the AOI simply doesn't overlap the event's
    real flood extent at all (compute_success_rate_curve's own "zero
    observed-flooded pixels" guard, which fires before
    compute_confusion_metrics ever gets a chance to raise the same
    thing) -- a genuinely different, expected case from a request-shape
    error, not conflated with one.
    """
    overlay_result = compute_overlay(aoi, criteria, final_weights, complete)
    mask_result = get_observed_flood_mask(aoi, event)

    success_rate = compute_success_rate_curve(
        overlay_result.risk_surface.risk_surface,
        overlay_result.risk_surface.nodata,
        mask_result.observed_flooded,
    )

    # Same discrete 1-5 hazard-class raster the map's own legend and
    # POST /report's high_risk_* figures already use -- confusion_metrics
    # scores against that established "High/Very High" operating point
    # rather than inventing a separate threshold rule for validation
    # alone. Derived fresh here rather than cached: it's a cheap
    # elementwise transform of an array already in memory, not worth its
    # own cache entry.
    hazard_classes = risk_surface_to_hazard_classes(
        overlay_result.risk_surface.risk_surface, overlay_result.risk_surface.nodata
    )
    confusion_metrics = compute_confusion_metrics(hazard_classes, HAZARD_CLASS_NODATA, mask_result.observed_flooded)

    attribution = sorted(set(overlay_result.attribution) | {mask_result.attribution})

    return ValidationResult(
        success_rate=success_rate,
        confusion_metrics=confusion_metrics,
        risk_surface_cache_key=overlay_result.cache_key,
        event=event,
        event_label=mask_result.label,
        attribution=attribution,
    )
