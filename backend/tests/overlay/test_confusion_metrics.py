"""Tests for app/overlay/confusion_metrics.py -- precision/recall/F1/IoU
at the High/Very-High hazard-class operating point, against hand-built
confusion matrices with known answers (not just "does it run").
"""

from __future__ import annotations

import numpy as np
import pytest

from app.overlay.confusion_metrics import compute_confusion_metrics
from app.overlay.errors import OverlayValidationError
from app.overlay.hazard_classes import HAZARD_CLASS_NODATA


def test_perfect_alignment_gives_precision_recall_f1_iou_all_one():
    """The same 3 rows are both High/Very-High hazard and really
    flooded, and nothing else is either -- a textbook perfect match.
    """
    hazard = np.ones((10, 10), dtype=np.uint8)
    hazard[:3, :] = 5
    observed = np.zeros((10, 10), dtype=np.uint8)
    observed[:3, :] = 1

    result = compute_confusion_metrics(hazard, HAZARD_CLASS_NODATA, observed)

    assert result.precision == pytest.approx(1.0)
    assert result.recall == pytest.approx(1.0)
    assert result.f1 == pytest.approx(1.0)
    assert result.iou == pytest.approx(1.0)
    assert result.true_positive == 30
    assert result.false_positive == 0
    assert result.false_negative == 0
    assert result.true_negative == 70


def test_disjoint_high_risk_and_flooded_areas_give_all_zero_metrics():
    """High/Very-High hazard is the top 3 rows; the real flooding is the
    bottom 3 rows -- zero overlap at all.
    """
    hazard = np.ones((10, 10), dtype=np.uint8)
    hazard[:3, :] = 5
    observed = np.zeros((10, 10), dtype=np.uint8)
    observed[7:, :] = 1

    result = compute_confusion_metrics(hazard, HAZARD_CLASS_NODATA, observed)

    assert result.precision == 0.0
    assert result.recall == 0.0
    assert result.f1 == 0.0
    assert result.iou == 0.0
    assert result.true_positive == 0
    assert result.false_positive == 30
    assert result.false_negative == 30
    assert result.true_negative == 40


def test_moderate_class_is_never_counted_as_predicted_positive():
    """Only hazard classes 4 (High) and 5 (Very High) count as
    "predicted flooded" -- class 3 (Moderate), even though it's above
    the "Low"/"Very Low" floor, must not be swept in.
    """
    hazard = np.full((10, 10), 3, dtype=np.uint8)  # every pixel "Moderate"
    observed = np.zeros((10, 10), dtype=np.uint8)
    observed[:3, :] = 1

    result = compute_confusion_metrics(hazard, HAZARD_CLASS_NODATA, observed)

    # Nothing is predicted positive at all -> zero-division convention.
    assert result.true_positive == 0
    assert result.false_positive == 0
    assert result.precision == 0.0
    assert result.recall == 0.0
    assert result.f1 == 0.0
    assert result.iou == 0.0


def test_partial_overlap_gives_a_real_intermediate_confusion_matrix():
    """A hand-computed partial-overlap case, not just the perfect/
    disjoint extremes: High/Very-High hazard = rows 0-4 (50 pixels),
    really flooded = rows 3-7 (50 pixels) -- rows 3-4 (20 pixels) overlap.
    """
    hazard = np.ones((10, 10), dtype=np.uint8)
    hazard[:5, :] = 4
    observed = np.zeros((10, 10), dtype=np.uint8)
    observed[3:8, :] = 1

    result = compute_confusion_metrics(hazard, HAZARD_CLASS_NODATA, observed)

    assert result.true_positive == 20  # rows 3-4
    assert result.false_positive == 30  # rows 0-2
    assert result.false_negative == 30  # rows 5-7
    assert result.true_negative == 20  # rows 8-9
    assert result.precision == pytest.approx(20 / 50)
    assert result.recall == pytest.approx(20 / 50)
    assert result.f1 == pytest.approx(20 / 50)  # precision == recall here
    assert result.iou == pytest.approx(20 / 80)  # 20 / (20+30+30)


def test_nodata_pixels_are_excluded_from_both_the_denominator_and_the_comparison():
    hazard = np.ones((10, 10), dtype=np.uint8)
    hazard[:3, :] = 5
    hazard[8:, :] = HAZARD_CLASS_NODATA  # last 2 rows: no risk-surface value there
    observed = np.zeros((10, 10), dtype=np.uint8)
    observed[:3, :] = 1
    observed[8:, :] = 1  # flagged "flooded" in a nodata area -- must not count

    result = compute_confusion_metrics(hazard, HAZARD_CLASS_NODATA, observed)

    assert result.true_positive + result.false_positive + result.false_negative + result.true_negative == 80
    assert result.precision == pytest.approx(1.0)
    assert result.recall == pytest.approx(1.0)


def test_mismatched_shapes_raise_validation_error():
    with pytest.raises(OverlayValidationError, match="shape"):
        compute_confusion_metrics(
            np.zeros((10, 10), dtype=np.uint8), HAZARD_CLASS_NODATA, np.zeros((10, 5), dtype=np.uint8)
        )


def test_all_nodata_raises_validation_error():
    hazard = np.full((10, 10), HAZARD_CLASS_NODATA, dtype=np.uint8)
    observed = np.zeros((10, 10), dtype=np.uint8)

    with pytest.raises(OverlayValidationError, match="no valid"):
        compute_confusion_metrics(hazard, HAZARD_CLASS_NODATA, observed)


def test_zero_observed_flooding_raises_validation_error():
    hazard = np.full((10, 10), 5, dtype=np.uint8)
    observed = np.zeros((10, 10), dtype=np.uint8)

    with pytest.raises(OverlayValidationError, match="zero observed-flooded"):
        compute_confusion_metrics(hazard, HAZARD_CLASS_NODATA, observed)
