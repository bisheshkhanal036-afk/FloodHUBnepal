"""Orchestration for POST /api/overlay/validate: computes the same risk
surface POST /api/overlay/compute would (reusing compute_overlay
directly, so this benefits from its own cache too — validating the same
AOI/criteria/weights twice never recomputes the risk surface itself),
rasterizes a real observed flood extent/inventory onto that exact same
grid, and scores the two against each other: the success-rate/AUC curve
(this app's own PRIMARY validation statistic, at explicit request — the
conceptually correct one for a susceptibility ranking) plus the
frequency-ratio-per-class check (does risk increase monotonically
across the 5 hazard classes — a simpler, directly communicable
complement to AUC, not a competing headline number).

Deliberately NOT a threshold-based confusion-matrix statistic
(precision/recall/F1/IoU) — this project's own prior discussion
established those answer "how good is one fixed threshold", the wrong
question for a ranking where the whole point is 5 ordered classes, not
a single yes/no cutoff. Removed entirely rather than kept-and-caveated.

Deliberately a thin orchestration layer, not new modeling logic:
compute_overlay (service.py), get_observed_flood_mask
(app/data/validation_extent.py), compute_success_rate_curve
(success_rate.py), and compute_frequency_ratio (frequency_ratio.py)
each already do their own real work; this module only wires them
together and shapes the result for the API response.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.data.aoi import AOI
from app.data.validation_extent import get_observed_flood_mask

from .frequency_ratio import FrequencyRatioResult, compute_frequency_ratio
from .hazard_classes import HAZARD_CLASS_NODATA, risk_surface_to_hazard_classes
from .service import OverlayCriterionRequest, compute_overlay
from .success_rate import SuccessRateResult, compute_success_rate_curve


@dataclass(frozen=True)
class ValidationResult:
    success_rate: SuccessRateResult
    frequency_ratio: FrequencyRatioResult
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
    real flood extent/inventory at all (compute_success_rate_curve's own
    "zero observed-flooded pixels" guard, which fires before
    compute_frequency_ratio is ever reached — that function itself does
    NOT raise on zero observed flooding, see its own docstring) — a
    genuinely different, expected case from a request-shape error, not
    conflated with one.
    """
    overlay_result = compute_overlay(aoi, criteria, final_weights, complete)
    mask_result = get_observed_flood_mask(aoi, event)

    success_rate = compute_success_rate_curve(
        overlay_result.risk_surface.risk_surface,
        overlay_result.risk_surface.nodata,
        mask_result.observed_flooded,
    )

    # Same discrete 1-5 hazard-class raster the map's own legend and
    # POST /report's high_risk_* figures already use. Derived fresh here
    # rather than cached: it's a cheap elementwise transform of an array
    # already in memory, not worth its own cache entry.
    hazard_classes = risk_surface_to_hazard_classes(
        overlay_result.risk_surface.risk_surface, overlay_result.risk_surface.nodata
    )
    frequency_ratio = compute_frequency_ratio(hazard_classes, HAZARD_CLASS_NODATA, mask_result.observed_flooded)

    attribution = sorted(set(overlay_result.attribution) | {mask_result.attribution})

    return ValidationResult(
        success_rate=success_rate,
        frequency_ratio=frequency_ratio,
        risk_surface_cache_key=overlay_result.cache_key,
        event=event,
        event_label=mask_result.label,
        attribution=attribution,
    )
