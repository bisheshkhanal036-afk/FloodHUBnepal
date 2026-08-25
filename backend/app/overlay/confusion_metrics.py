"""Confusion-matrix metrics (precision, recall, F1, IoU) for a computed
risk surface against a real, satellite-observed flood extent -- the
threshold-based counterpart to success_rate.py's own threshold-free
AUC/PR-AUC. Where those sweep every possible cutoff, this module scores
ONE single, already-meaningful operating point: hazard classes 4 (High)
and 5 (Very High) -- see hazard_classes.HIGH_RISK_CLASSES's own docstring
for why that exact set, not an arbitrary top-k cutoff, is the right
"predicted flooded" line to draw. That's also the only classification
threshold this app exposes to a user anywhere else (the map's own
hazard-class legend, and report.py's high_risk_building_count/
high_risk_population figures) -- reusing it here means "precision" and
"recall" answer the same question a user would actually ask: "of the
area I labeled High/Very High risk, how much really flooded, and of
what really flooded, how much did I label High/Very High?"

Deliberately takes the discrete hazard-class raster, not the continuous
risk_surface -- confusion-matrix metrics need a binary predicted-
positive/negative split, and hazard_classes.py's own round-nearest
discretization is already this app's one true way to turn the continuous
score into that split, rather than reinventing a second threshold rule
here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import OverlayValidationError
from .hazard_classes import HIGH_RISK_CLASSES


@dataclass(frozen=True)
class ConfusionMetricsResult:
    precision: float
    recall: float
    f1: float
    iou: float
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int


_DEFAULT_ZERO_POSITIVE_HINT = (
    "this AOI likely doesn't overlap the validation event's own real flood extent "
    "(see config.VALIDATION_EVENTS for what each event actually covers)"
)


def compute_confusion_metrics(
    hazard_classes: np.ndarray,
    hazard_nodata: int,
    observed_flooded: np.ndarray,
    zero_positive_hint: str = _DEFAULT_ZERO_POSITIVE_HINT,
) -> ConfusionMetricsResult:
    """`hazard_classes` and `observed_flooded` must already be on the
    exact same grid, the same contract success_rate.compute_success_rate_curve
    has with its own two array arguments. `observed_flooded` is generic
    over what "flooded" means the same way that module's own docstring
    explains -- real satellite-observed data, or meteor_comparison.py's
    METEOR-modeled mask; `zero_positive_hint` lets each caller's own
    zero-positive error message stay accurate to which one it was.

    Only pixels where `hazard_classes != hazard_nodata` are compared --
    same nodata-excluded-from-both-sides reasoning as
    compute_success_rate_curve. "Predicted flooded" is
    `hazard_class in HIGH_RISK_CLASSES`; "predicted not flooded" is any
    other real class (1-3).

    Raises OverlayValidationError for a shape mismatch, no valid pixels
    at all, or zero observed-flooded pixels in the valid area (the same
    AOI-doesn't-overlap-the-event case compute_success_rate_curve
    already guards against -- recall is undefined with nothing to
    recall).

    precision and f1 are defined as 0.0 (not NaN, and not an error) when
    the model predicts NOTHING as high-risk anywhere in the valid area
    (true_positive + false_positive == 0) -- the standard zero-division
    convention (matching scikit-learn's own default), since "the model
    made zero high-risk predictions" is a real, valid, if unhelpful,
    result to report rather than something to reject.
    """
    if hazard_classes.shape != observed_flooded.shape:
        raise OverlayValidationError(
            f"confusion_metrics: hazard_classes shape {hazard_classes.shape} != "
            f"observed_flooded shape {observed_flooded.shape} -- they must be on the same grid"
        )

    valid_mask = hazard_classes != hazard_nodata
    valid_classes = hazard_classes[valid_mask]
    valid_observed = observed_flooded[valid_mask].astype(bool)

    if valid_classes.size == 0:
        raise OverlayValidationError(
            "confusion_metrics: no valid (non-nodata) hazard-class pixels in this AOI to validate against"
        )

    n_flooded = int(valid_observed.sum())
    if n_flooded == 0:
        raise OverlayValidationError(
            f"confusion_metrics: zero observed-flooded pixels within this AOI's valid area -- {zero_positive_hint}"
        )

    predicted_positive = np.isin(valid_classes, HIGH_RISK_CLASSES)

    tp = int(np.count_nonzero(predicted_positive & valid_observed))
    fp = int(np.count_nonzero(predicted_positive & ~valid_observed))
    fn = int(np.count_nonzero(~predicted_positive & valid_observed))
    tn = int(np.count_nonzero(~predicted_positive & ~valid_observed))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    # recall's own denominator (tp + fn == n_flooded) is guaranteed > 0
    # by the zero-observed-flooding guard above, so this can never
    # itself hit the same zero-division case precision's can.
    recall = tp / (tp + fn)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    iou = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0.0

    return ConfusionMetricsResult(
        precision=precision,
        recall=recall,
        f1=f1,
        iou=iou,
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        true_negative=tn,
    )
