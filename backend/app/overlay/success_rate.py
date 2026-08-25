"""Success-rate curve / AUC: the standard validation method for an
index-based flood-susceptibility map (already named, not newly invented
here, in config/literature.js's own METHOD_INTRO: "validated against an
observed flood inventory (success-rate / AUC)", citing Chung & Fabbri's
original method as applied in this project's own cited literature --
Kazakis et al. 2015, Das 2019).

The idea: sort every pixel in the AOI by the model's own continuous risk
score, highest first. Walk down that ranking accumulating area; a good
model should capture a disproportionate share of the REAL observed
flooding within the smallest possible cumulative area (i.e. its
highest-risk pixels really were the ones that flooded). Plotting
cumulative-area-fraction (x) against cumulative-observed-flooding-
captured (y) traces the success-rate curve; the area under it (AUC) is
the single summary statistic -- 0.5 is what an uninformative
(random-order) ranking produces, 1.0 is a perfect one.

Deliberately NOT compared against METEOR's own modeled hazard output --
see this project's own prior discussion on why that only checks
agreement between two models, not real-world accuracy. This module
compares against app/data/validation_extent.py's real satellite-
observed flood extent instead.

Also computes the precision-recall curve and its own area (PR-AUC) from
that exact same descending-risk ranking, since both curves are just two
different plots of the identical sweep -- rank every pixel by risk,
score.  Walk down that ranking one cutoff at a time (top-1 highest-risk
pixel predicted positive, top-2, ...); at each cutoff k the success-rate
curve's own y-axis (cumulative observed flooding captured / total
observed flooding) IS recall by definition, so no new computation is
needed for that half. The only new quantity is precision at each cutoff
(captured flooding / k, i.e. of the k pixels predicted positive at this
cutoff, what fraction really flooded) -- computed from the exact same
`cum_flooded` array success_rate's own curve already builds. Unlike the
success-rate curve's own AUC (whose random-ranking baseline is a fixed
0.5 regardless of the flooded fraction), PR-AUC's own uninformative
baseline is the flooded fraction itself (a random ranking's precision
hovers around the base rate at every cutoff) -- callers should compare
pr_auc against `observed_flooded_fraction`, not against 0.5.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import OverlayValidationError


@dataclass(frozen=True)
class SuccessRateResult:
    auc: float
    # (cumulative_area_fraction, cumulative_capture_fraction) pairs,
    # 0.0 to 1.0 on both axes, n_bins+1 points including both endpoints
    # -- enough to plot a real curve, not just report the scalar AUC.
    curve: list[tuple[float, float]]
    # Area under the precision-recall curve below -- see this module's
    # own docstring for why its baseline is observed_flooded_fraction,
    # not 0.5.
    pr_auc: float
    # (recall, precision) pairs, same n_bins+1 cutoffs as `curve` above
    # (recall at each cutoff is literally `curve`'s own y-value at that
    # same point) -- plot directly as the precision-recall curve.
    precision_recall_curve: list[tuple[float, float]]
    n_valid_pixels: int
    n_observed_flooded_pixels: int
    observed_flooded_fraction: float


_DEFAULT_ZERO_POSITIVE_HINT = (
    "this AOI likely doesn't overlap the validation event's own real flood extent "
    "(see config.VALIDATION_EVENTS for what each event actually covers)"
)


def compute_success_rate_curve(
    risk_surface: np.ndarray,
    nodata: float,
    observed_flooded: np.ndarray,
    n_bins: int = 100,
    zero_positive_hint: str = _DEFAULT_ZERO_POSITIVE_HINT,
) -> SuccessRateResult:
    """`risk_surface` and `observed_flooded` must already be on the exact
    same grid (same shape, same pixel-for-pixel meaning) -- this function
    does no reprojection or resampling of its own; that's
    validation_extent.py's job, by construction always rasterizing onto
    whatever grid the risk surface for the same AOI is already on.

    Only pixels where `risk_surface != nodata` are compared -- an area
    the risk surface itself couldn't produce a value for (e.g. a
    criterion's own local coverage gap) is excluded from both the
    denominator and the observed-flooding count, rather than silently
    counted as either "no risk" or "no flooding".

    Genuinely generic over what `observed_flooded` represents -- not just
    a real, satellite-observed flood extent (this function's original,
    still most common caller, hence the parameter name and this
    docstring's own default vocabulary), but equally meteor_comparison.py's
    METEOR-modeled flood mask, or any other 0/1 "did this pixel flood"
    array on the same grid. `zero_positive_hint` exists solely so each
    caller's own zero-positive-pixels error message stays accurate to
    what it actually compared against, without this function needing to
    know or guess which one produced its input.

    Raises OverlayValidationError if the two arrays don't share a shape,
    if there are no valid risk-surface pixels to compare at all, or if
    the valid area contains zero observed-flooded pixels (a curve/AUC is
    undefined with nothing to capture -- this is the AOI-doesn't-overlap-
    the-event case, not a "model failed" result).
    """
    if risk_surface.shape != observed_flooded.shape:
        raise OverlayValidationError(
            f"success_rate: risk_surface shape {risk_surface.shape} != "
            f"observed_flooded shape {observed_flooded.shape} -- they must be on the same grid"
        )

    valid_mask = risk_surface != nodata
    valid_risk = risk_surface[valid_mask]
    valid_observed = observed_flooded[valid_mask].astype(bool)
    n_valid = int(valid_risk.size)

    if n_valid == 0:
        raise OverlayValidationError(
            "success_rate: no valid (non-nodata) risk-surface pixels in this AOI to validate against"
        )

    n_flooded = int(valid_observed.sum())
    if n_flooded == 0:
        raise OverlayValidationError(
            f"success_rate: zero observed-flooded pixels within this AOI's valid risk-surface area -- {zero_positive_hint}"
        )

    # Descending by risk score: index 0 is the single highest-risk pixel.
    order = np.argsort(-valid_risk, kind="stable")
    sorted_observed = valid_observed[order]
    cum_flooded = np.cumsum(sorted_observed)

    area_fracs = np.linspace(0.0, 1.0, n_bins + 1)
    pixel_counts = np.round(area_fracs * n_valid).astype(np.int64)
    # capture fraction at 0 area is always 0 by definition; cum_flooded is
    # 1-indexed by pixel count, so the pixel at position k (1-based) is
    # cum_flooded[k-1].
    capture_fracs = np.where(
        pixel_counts > 0, cum_flooded[np.clip(pixel_counts, 1, n_valid) - 1] / n_flooded, 0.0
    )

    auc = float(np.trapezoid(capture_fracs, area_fracs))

    # Precision at each of the same cutoffs: of the `pixel_counts[i]`
    # highest-risk pixels predicted positive at that cutoff, what
    # fraction really flooded. At the k=0 cutoff (predicting nothing
    # positive) precision is mathematically undefined -- defined as 1.0
    # here, the same boundary convention scikit-learn's own
    # precision_recall_curve uses at its highest-threshold endpoint,
    # rather than an arbitrary 0.0 that would understate the curve.
    safe_pixel_counts = np.clip(pixel_counts, 1, n_valid)
    precision_fracs = np.where(
        pixel_counts > 0, cum_flooded[safe_pixel_counts - 1] / safe_pixel_counts, 1.0
    )
    # x = recall (capture_fracs), which is non-decreasing in area_fracs
    # by construction (a cumulative sum of a 0/1 array can never
    # decrease) -- trapezoid over it is a real area, not just a sum
    # over an arbitrarily-ordered sequence.
    pr_auc = float(np.trapezoid(precision_fracs, capture_fracs))

    return SuccessRateResult(
        auc=auc,
        curve=list(zip(area_fracs.tolist(), capture_fracs.tolist())),
        pr_auc=pr_auc,
        precision_recall_curve=list(zip(capture_fracs.tolist(), precision_fracs.tolist())),
        n_valid_pixels=n_valid,
        n_observed_flooded_pixels=n_flooded,
        observed_flooded_fraction=n_flooded / n_valid,
    )
