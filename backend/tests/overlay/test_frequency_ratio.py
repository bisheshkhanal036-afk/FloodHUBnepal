"""Tests for app/overlay/frequency_ratio.py -- the "does risk increase
monotonically across classes" check, against hand-built hazard-class
rasters with known answers.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.overlay.errors import OverlayValidationError
from app.overlay.frequency_ratio import compute_frequency_ratio
from app.overlay.hazard_classes import HAZARD_CLASS_LABELS, HAZARD_CLASS_NODATA


def test_perfectly_monotonic_classes_are_flagged_monotonic():
    """5 equal-size bands, class k's own flooded fraction is exactly
    k*10% -- a textbook monotonic-increasing case.
    """
    hazard = np.zeros((50, 10), dtype=np.uint8)
    observed = np.zeros((50, 10), dtype=np.uint8)
    for k in range(1, 6):
        rows = slice((k - 1) * 10, k * 10)
        hazard[rows, :] = k
        # k*1 flooded rows out of 10 -> flooded_fraction = k/10
        observed[rows][:k, :] = 1

    result = compute_frequency_ratio(hazard, HAZARD_CLASS_NODATA, observed)

    assert result.monotonic is True
    fractions = [c.flooded_fraction for c in result.by_class]
    assert fractions == [pytest.approx(k / 10) for k in range(1, 6)]
    assert [c.hazard_class for c in result.by_class] == [1, 2, 3, 4, 5]
    assert [c.hazard_label for c in result.by_class] == [HAZARD_CLASS_LABELS[k] for k in range(1, 6)]


def test_non_monotonic_classes_are_flagged_not_monotonic():
    """Class 3 floods MORE than class 4 -- a real, detectable inversion."""
    hazard = np.zeros((50, 10), dtype=np.uint8)
    observed = np.zeros((50, 10), dtype=np.uint8)
    hazard[0:10, :] = 1
    hazard[10:20, :] = 2
    hazard[20:30, :] = 3
    observed[20:30][:8, :] = 1  # class 3: 80% flooded
    hazard[30:40, :] = 4
    observed[30:40][:2, :] = 1  # class 4: 20% flooded -- lower than class 3
    hazard[40:50, :] = 5
    observed[40:50][:9, :] = 1  # class 5: 90% flooded

    result = compute_frequency_ratio(hazard, HAZARD_CLASS_NODATA, observed)

    assert result.monotonic is False
    by_class = {c.hazard_class: c.flooded_fraction for c in result.by_class}
    assert by_class[3] == pytest.approx(0.8)
    assert by_class[4] == pytest.approx(0.2)


def test_a_class_absent_from_the_aoi_gets_none_not_zero_and_is_skipped_in_the_monotonicity_check():
    """Only classes 1, 3, 5 occur in this AOI -- class 2 and 4 must come
    back as flooded_fraction=None (not 0.0, which would misleadingly
    claim "this class occurs and never floods"), and the monotonicity
    check must compare 1 -> 3 -> 5 directly, skipping the gaps.
    """
    hazard = np.zeros((30, 10), dtype=np.uint8)
    observed = np.zeros((30, 10), dtype=np.uint8)
    hazard[0:10, :] = 1
    observed[0:10][:1, :] = 1  # class 1: 10%
    hazard[10:20, :] = 3
    observed[10:20][:5, :] = 1  # class 3: 50%
    hazard[20:30, :] = 5
    observed[20:30][:9, :] = 1  # class 5: 90%

    result = compute_frequency_ratio(hazard, HAZARD_CLASS_NODATA, observed)

    by_class = {c.hazard_class: c.flooded_fraction for c in result.by_class}
    assert by_class[2] is None
    assert by_class[4] is None
    assert by_class[1] == pytest.approx(0.1)
    assert by_class[3] == pytest.approx(0.5)
    assert by_class[5] == pytest.approx(0.9)
    assert result.monotonic is True
    # All 5 classes still present in the result, absent or not.
    assert [c.hazard_class for c in result.by_class] == [1, 2, 3, 4, 5]


def test_pixel_counts_and_flooded_pixel_counts_are_exact():
    hazard = np.full((10, 10), 4, dtype=np.uint8)
    observed = np.zeros((10, 10), dtype=np.uint8)
    observed[:3, :] = 1  # 30 flooded pixels

    result = compute_frequency_ratio(hazard, HAZARD_CLASS_NODATA, observed)

    class_4 = next(c for c in result.by_class if c.hazard_class == 4)
    assert class_4.pixel_count == 100
    assert class_4.flooded_pixel_count == 30
    assert class_4.flooded_fraction == pytest.approx(0.3)
    for c in result.by_class:
        if c.hazard_class != 4:
            assert c.pixel_count == 0
            assert c.flooded_pixel_count == 0
            assert c.flooded_fraction is None


def test_nodata_pixels_are_excluded():
    hazard = np.full((10, 10), 5, dtype=np.uint8)
    hazard[8:, :] = HAZARD_CLASS_NODATA
    observed = np.ones((10, 10), dtype=np.uint8)

    result = compute_frequency_ratio(hazard, HAZARD_CLASS_NODATA, observed)

    class_5 = next(c for c in result.by_class if c.hazard_class == 5)
    assert class_5.pixel_count == 80  # not 100 -- the 2 nodata rows are excluded


def test_zero_observed_flooding_gives_all_zero_fractions_and_vacuously_monotonic():
    """Unlike success_rate.compute_success_rate_curve, this does NOT
    raise on zero observed flooding -- every class's own fraction is
    simply 0.0, a real if uninteresting answer.
    """
    hazard = np.zeros((50, 10), dtype=np.uint8)
    for k in range(1, 6):
        hazard[(k - 1) * 10 : k * 10, :] = k
    observed = np.zeros((50, 10), dtype=np.uint8)

    result = compute_frequency_ratio(hazard, HAZARD_CLASS_NODATA, observed)

    assert result.monotonic is True
    assert all(c.flooded_fraction == 0.0 for c in result.by_class)


def test_mismatched_shapes_raise_validation_error():
    with pytest.raises(OverlayValidationError, match="shape"):
        compute_frequency_ratio(
            np.zeros((10, 10), dtype=np.uint8), HAZARD_CLASS_NODATA, np.zeros((10, 5), dtype=np.uint8)
        )


def test_all_nodata_raises_validation_error():
    hazard = np.full((10, 10), HAZARD_CLASS_NODATA, dtype=np.uint8)
    observed = np.zeros((10, 10), dtype=np.uint8)

    with pytest.raises(OverlayValidationError, match="no valid"):
        compute_frequency_ratio(hazard, HAZARD_CLASS_NODATA, observed)
