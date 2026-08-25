"""Frequency ratio per hazard class -- "does risk increase monotonically
across classes": for each discrete hazard class 1-5, what fraction of
that class's own pixels actually flooded in the validation reference?
A well-behaved susceptibility map should show this fraction increase
(or at least never decrease) from class 1 (Very Low) to class 5 (Very
High) -- the model's own risk ORDERING should track a real, monotonic
increase in actual flood occurrence.

Standard practice in the flood/landslide susceptibility literature
(e.g. Lee & Pradhan 2007's own "frequency ratio" method), and a
deliberately different, complementary question from success_rate.py's
own AUC: that curve answers "how good is the ranking overall, swept
over every possible cutoff"; this answers "does each individual class
actually mean what it claims to mean" -- a simpler, more directly
communicable per-class sanity check, not a replacement for AUC as the
model's own headline validation statistic.

Deliberately NOT a confusion-matrix statistic (precision/recall/F1/
IoU) -- this project's own prior discussion established those answer
"how good is one fixed threshold", the wrong question for a
susceptibility RANKING, where the whole point is that risk is relative
across 5 ordered classes, not a single yes/no cutoff.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import OverlayValidationError
from .hazard_classes import HAZARD_CLASS_LABELS


@dataclass(frozen=True)
class ClassFrequencyRatio:
    hazard_class: int
    hazard_label: str
    pixel_count: int
    flooded_pixel_count: int
    # None, not 0.0, when pixel_count == 0 -- this class simply doesn't
    # occur anywhere in this AOI (e.g. a small, uniformly flat AOI might
    # never produce a "Very Low" pixel at all), a different situation
    # from "this class occurs but nothing in it ever flooded" (a real
    # 0.0). Excluded from the monotonicity check below for the same
    # reason: an absent class has no real ratio to compare.
    flooded_fraction: float | None


@dataclass(frozen=True)
class FrequencyRatioResult:
    # Always all 5 classes, in ascending order (1..5) -- classes absent
    # from this AOI still appear, with flooded_fraction=None, so a
    # caller never has to guess whether a missing entry means "0%
    # flooded" or "doesn't occur here".
    by_class: list[ClassFrequencyRatio]
    # True iff flooded_fraction is non-decreasing across every
    # consecutive PAIR of classes that both actually occur in this AOI
    # (absent classes are skipped, not treated as a break in the
    # sequence) -- vacuously True if fewer than 2 classes occur at all.
    monotonic: bool


def compute_frequency_ratio(
    hazard_classes: np.ndarray, hazard_nodata: int, observed_flooded: np.ndarray
) -> FrequencyRatioResult:
    """Same nodata-excluded-from-both-sides contract as
    success_rate.compute_success_rate_curve's own risk_surface/
    observed_flooded pair -- only pixels where
    `hazard_classes != hazard_nodata` are compared.

    Raises OverlayValidationError for a shape mismatch or no valid
    pixels at all. Unlike compute_success_rate_curve, does NOT raise on
    zero observed-flooded pixels -- every class's own flooded_fraction
    is simply 0.0 in that case (a real, if uninteresting, answer: "this
    reference event doesn't overlap this AOI at all"), and monotonic is
    vacuously True. Callers that need to reject that case do so via
    compute_success_rate_curve's own guard, which every current caller
    (validate.py, meteor_comparison.py) already calls first in the same
    request.
    """
    if hazard_classes.shape != observed_flooded.shape:
        raise OverlayValidationError(
            f"frequency_ratio: hazard_classes shape {hazard_classes.shape} != "
            f"observed_flooded shape {observed_flooded.shape} -- they must be on the same grid"
        )

    valid_mask = hazard_classes != hazard_nodata
    valid_classes = hazard_classes[valid_mask]
    valid_observed = observed_flooded[valid_mask].astype(bool)

    if valid_classes.size == 0:
        raise OverlayValidationError(
            "frequency_ratio: no valid (non-nodata) hazard-class pixels in this AOI to validate against"
        )

    by_class: list[ClassFrequencyRatio] = []
    for hazard_class in range(1, 6):
        class_mask = valid_classes == hazard_class
        pixel_count = int(np.count_nonzero(class_mask))
        flooded_count = int(np.count_nonzero(class_mask & valid_observed))
        fraction = (flooded_count / pixel_count) if pixel_count > 0 else None
        by_class.append(
            ClassFrequencyRatio(
                hazard_class=hazard_class,
                hazard_label=HAZARD_CLASS_LABELS[hazard_class],
                pixel_count=pixel_count,
                flooded_pixel_count=flooded_count,
                flooded_fraction=fraction,
            )
        )

    present_fractions = [c.flooded_fraction for c in by_class if c.flooded_fraction is not None]
    monotonic = all(present_fractions[i] <= present_fractions[i + 1] for i in range(len(present_fractions) - 1))

    return FrequencyRatioResult(by_class=by_class, monotonic=monotonic)
