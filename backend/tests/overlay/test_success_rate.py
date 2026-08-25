"""Tests for app/overlay/success_rate.py -- the success-rate curve / AUC
validation metric. Verified against synthetic perfect/random/inverse
rankings with known closed-form AUC values (for a positive fraction p:
perfect ranking -> AUC = 1 - p/2, inverse ranking -> AUC = p/2, random
-> AUC ~= 0.5), not just "does it run".
"""

from __future__ import annotations

import numpy as np
import pytest

from app.overlay.errors import OverlayValidationError
from app.overlay.success_rate import compute_success_rate_curve

RISK_SURFACE_NODATA = -9999.0


def _synthetic(n=10000, flooded_fraction=0.05, seed=42):
    rng = np.random.default_rng(seed)
    n_flooded = int(n * flooded_fraction)
    observed = np.zeros(n, dtype=np.uint8)
    observed[:n_flooded] = 1
    rng.shuffle(observed)
    return observed, n_flooded


def test_perfect_ranking_matches_the_closed_form_auc():
    """A risk score that exactly equals the observed label (flooded
    pixels all rank highest) has a known closed-form AUC: 1 - p/2, where
    p is the flooded fraction.
    """
    observed, n_flooded = _synthetic(n=10000, flooded_fraction=0.05)
    risk = observed.astype(np.float32)

    result = compute_success_rate_curve(risk, RISK_SURFACE_NODATA, observed, n_bins=200)

    assert result.auc == pytest.approx(1 - 0.05 / 2, abs=0.01)
    assert result.n_observed_flooded_pixels == n_flooded
    assert result.observed_flooded_fraction == pytest.approx(0.05, abs=0.001)


def test_inverse_ranking_matches_the_closed_form_auc():
    """The worst possible ranking (flooded pixels all rank lowest) has
    closed-form AUC p/2 -- the mirror image of the perfect case.
    """
    observed, _ = _synthetic(n=10000, flooded_fraction=0.05)
    risk = (1 - observed).astype(np.float32)

    result = compute_success_rate_curve(risk, RISK_SURFACE_NODATA, observed, n_bins=200)

    assert result.auc == pytest.approx(0.05 / 2, abs=0.01)


def test_random_ranking_gives_auc_near_one_half():
    observed, _ = _synthetic(n=20000, flooded_fraction=0.1)
    rng = np.random.default_rng(7)
    risk = rng.random(observed.shape).astype(np.float32)

    result = compute_success_rate_curve(risk, RISK_SURFACE_NODATA, observed, n_bins=200)

    assert result.auc == pytest.approx(0.5, abs=0.02)


def test_curve_starts_at_origin_and_ends_at_one_one():
    observed, _ = _synthetic()
    risk = observed.astype(np.float32)

    result = compute_success_rate_curve(risk, RISK_SURFACE_NODATA, observed, n_bins=50)

    assert result.curve[0] == (0.0, 0.0)
    assert result.curve[-1] == (1.0, 1.0)
    assert len(result.curve) == 51


def test_nodata_pixels_are_excluded_from_both_the_denominator_and_the_comparison():
    """A pixel where the risk surface itself has no value must not count
    toward n_valid_pixels or the flooded count -- confirmed by comparing
    against the same scenario with those pixels absent entirely.
    """
    observed, n_flooded = _synthetic(n=1000, flooded_fraction=0.1)
    risk = observed.astype(np.float32)

    # Extend with 500 nodata pixels, some flagged as "observed flooded"
    # (which must NOT count, since the risk surface has no opinion there).
    extra_observed = np.zeros(500, dtype=np.uint8)
    extra_observed[:50] = 1
    risk_with_nodata = np.concatenate([risk, np.full(500, RISK_SURFACE_NODATA, dtype=np.float32)])
    observed_with_nodata = np.concatenate([observed, extra_observed])

    result = compute_success_rate_curve(risk_with_nodata, RISK_SURFACE_NODATA, observed_with_nodata, n_bins=50)

    assert result.n_valid_pixels == 1000
    assert result.n_observed_flooded_pixels == n_flooded


def test_mismatched_shapes_raise_validation_error():
    with pytest.raises(OverlayValidationError, match="shape"):
        compute_success_rate_curve(
            np.zeros((10, 10), dtype=np.float32), RISK_SURFACE_NODATA, np.zeros((10, 5), dtype=np.uint8)
        )


def test_all_nodata_raises_validation_error():
    risk = np.full(100, RISK_SURFACE_NODATA, dtype=np.float32)
    observed = np.zeros(100, dtype=np.uint8)

    with pytest.raises(OverlayValidationError, match="no valid"):
        compute_success_rate_curve(risk, RISK_SURFACE_NODATA, observed)


def test_zero_observed_flooding_raises_validation_error():
    """The AOI-doesn't-overlap-the-event case: a real risk surface, but
    zero real flooding anywhere in it -- a curve/AUC is undefined, not
    just uninteresting, since there's nothing to capture.
    """
    risk = np.random.default_rng(1).random(1000).astype(np.float32)
    observed = np.zeros(1000, dtype=np.uint8)

    with pytest.raises(OverlayValidationError, match="zero observed-flooded"):
        compute_success_rate_curve(risk, RISK_SURFACE_NODATA, observed)


def test_perfect_ranking_gives_pr_auc_near_one():
    """A risk score exactly equal to the observed label puts every truly
    flooded pixel at the very top of the ranking -- precision stays 1.0
    all the way out to recall=1.0 (the first n_flooded cutoffs are all
    correct), so pr_auc should be close to 1.0, not the closed-form
    success-rate value.
    """
    observed, _ = _synthetic(n=10000, flooded_fraction=0.05)
    risk = observed.astype(np.float32)

    result = compute_success_rate_curve(risk, RISK_SURFACE_NODATA, observed, n_bins=200)

    assert result.pr_auc > 0.95


def test_random_ranking_gives_pr_auc_near_the_base_rate_not_one_half():
    """Unlike the success-rate AUC's fixed 0.5 random baseline, PR-AUC's
    own uninformative baseline is the flooded fraction itself.
    """
    observed, _ = _synthetic(n=20000, flooded_fraction=0.1)
    rng = np.random.default_rng(7)
    risk = rng.random(observed.shape).astype(np.float32)

    result = compute_success_rate_curve(risk, RISK_SURFACE_NODATA, observed, n_bins=200)

    assert result.pr_auc == pytest.approx(0.1, abs=0.03)


def test_precision_recall_curve_starts_at_recall_zero_precision_one_and_ends_at_recall_one():
    observed, _ = _synthetic()
    risk = observed.astype(np.float32)

    result = compute_success_rate_curve(risk, RISK_SURFACE_NODATA, observed, n_bins=50)

    assert result.precision_recall_curve[0] == (0.0, 1.0)
    assert result.precision_recall_curve[-1][0] == pytest.approx(1.0)
    assert len(result.precision_recall_curve) == 51


def test_works_on_2d_arrays_like_a_real_risk_surface_and_mask():
    """The real caller passes 2D (height, width) arrays, not the
    flattened 1D arrays the synthetic tests above use for convenience --
    confirm the function handles that shape directly (numpy boolean
    indexing already flattens internally, but this pins the real usage
    shape as a regression guard).
    """
    risk = np.zeros((50, 50), dtype=np.float32)
    observed = np.zeros((50, 50), dtype=np.uint8)
    risk[:5, :] = 1.0
    observed[:5, :] = 1

    result = compute_success_rate_curve(risk, RISK_SURFACE_NODATA, observed, n_bins=20)

    assert result.n_valid_pixels == 2500
    assert result.n_observed_flooded_pixels == 250
    assert result.auc > 0.9
