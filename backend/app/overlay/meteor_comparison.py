"""Compares a computed risk surface against METEOR's own modeled flood
hazard (app/data/meteor_flood.py) -- at the user's own explicit request,
after this project's earlier discussion established that a METEOR
comparison checks *agreement between two models*, not real-world
accuracy (that question -- validation against a real, satellite-
observed flood extent -- is validate.py's own job, a genuinely different
thing). This module answers a real, useful, but DIFFERENT question:
"where this app's own risk surface and METEOR's independently-produced
one disagree, where do they agree" -- worth knowing, never a substitute
for the real thing.

Deliberately kept as its own module/endpoint/UI section for exactly that
reason: it reuses success_rate.py's and confusion_metrics.py's own
comparison machinery (both fully generic over what the "second mask"
represents -- see their own docstrings) but is never merged into
validate.py's own event list or exposed through "Validate" language
anywhere in the API or the frontend. A model-agreement result must never
read as if it were validation against ground truth.

--- Binarizing METEOR's continuous depth into a flooded/not-flooded mask ---

METEOR's own depth_m is continuous meters, already fully resolved (see
meteor_flood.py's own docstring): 0.0 means "no modeled flood hazard
here", any positive value is a real modeled depth, and the rare
permanent-water sentinel is remapped to a fixed 5.0m. `depth_m > 0.0` is
therefore exactly "METEOR models any flood hazard at all at this pixel"
-- the same depth-nonzero convention flood-model intercomparison studies
standardly use to derive a binary extent from a continuous depth grid,
not a threshold invented for this module alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.data import config
from app.data.aoi import AOI
from app.data.meteor_flood import get_meteor_flood_hazard

from .confusion_metrics import ConfusionMetricsResult, compute_confusion_metrics
from .hazard_classes import HAZARD_CLASS_NODATA, risk_surface_to_hazard_classes
from .service import OverlayCriterionRequest, compute_overlay
from .success_rate import SuccessRateResult, compute_success_rate_curve

_ZERO_METEOR_FLOODED_HINT = (
    "this AOI falls entirely outside METEOR's own modeled floodplain domain for the "
    "configured flood_type/return_period (a real, expected result for terrain METEOR's "
    "own model never expects to flood, e.g. a hillslope or ridge -- not a bug, and not "
    "evidence this app's own risk surface is wrong)"
)


@dataclass(frozen=True)
class MeteorComparisonResult:
    success_rate: SuccessRateResult
    confusion_metrics: ConfusionMetricsResult
    risk_surface_cache_key: str
    meteor_flood_type: str
    meteor_return_period: str
    attribution: list[str]


def compare_risk_surface_to_meteor(
    aoi: AOI,
    criteria: list[OverlayCriterionRequest],
    final_weights: dict[str, float],
    complete: bool,
) -> MeteorComparisonResult:
    """Same shape and same caching behavior as validate.validate_risk_surface
    (reuses compute_overlay directly, so an AOI/criteria/weights
    combination already computed via POST /compute or POST /validate is
    not recomputed here either) -- see that module's own docstring for
    the exceptions this can raise; identical here, with
    get_meteor_flood_hazard (app/data/meteor_flood.py) standing in for
    get_observed_flood_mask (app/data/validation_extent.py) as the
    "second mask" source. get_meteor_flood_hazard raises
    DataSourceUnavailableError under the exact same condition
    get_observed_flood_mask's own local-file check does: no local METEOR
    GeoTIFF downloaded for the configured flood_type/return_period.

    Note one real difference from validate_risk_surface: `criteria` here
    may legitimately include a `flood_hazard_meteor` criterion itself
    (overlay/sources.py registers METEOR as one AHP input among several,
    at explicit prior request) -- comparing a risk surface that already
    partly incorporates METEOR against METEOR again is still a
    meaningful agreement check (it answers "how much did including
    METEOR as an input actually change where this surface agrees with
    METEOR overall", not a circular one), so this module doesn't reject
    or special-case that combination.
    """
    overlay_result = compute_overlay(aoi, criteria, final_weights, complete)
    meteor_result = get_meteor_flood_hazard(aoi)

    meteor_flooded = (meteor_result.depth_m > 0.0) & (meteor_result.depth_m != meteor_result.nodata)

    success_rate = compute_success_rate_curve(
        overlay_result.risk_surface.risk_surface,
        overlay_result.risk_surface.nodata,
        meteor_flooded,
        zero_positive_hint=_ZERO_METEOR_FLOODED_HINT,
    )

    hazard_classes = risk_surface_to_hazard_classes(
        overlay_result.risk_surface.risk_surface, overlay_result.risk_surface.nodata
    )
    confusion_metrics = compute_confusion_metrics(
        hazard_classes, HAZARD_CLASS_NODATA, meteor_flooded, zero_positive_hint=_ZERO_METEOR_FLOODED_HINT
    )

    attribution = sorted(set(overlay_result.attribution) | {meteor_result.attribution})

    return MeteorComparisonResult(
        success_rate=success_rate,
        confusion_metrics=confusion_metrics,
        risk_surface_cache_key=overlay_result.cache_key,
        meteor_flood_type=config.METEOR_FLOOD_TYPE,
        meteor_return_period=config.METEOR_FLOOD_RETURN_PERIOD,
        attribution=attribution,
    )
