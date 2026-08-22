from __future__ import annotations

import numpy as np
import pytest

from app.data.errors import ReclassificationError
from app.data.reclassify import (
    RECLASSIFIED_NODATA,
    apply_reclassification,
    apply_reclassification_cached,
    rules_fingerprint,
    validate_reclassification_rules,
)

# Example slope-in-degrees thresholds, shaped exactly like
# schemas/criterion.schema.json's reclassificationRule, covering [0, inf).
SLOPE_RULES = [
    {"min": 0, "max": 2, "min_inclusive": True, "max_inclusive": False, "risk_class": 5},
    {"min": 2, "max": 5, "min_inclusive": True, "max_inclusive": False, "risk_class": 4},
    {"min": 5, "max": 15, "min_inclusive": True, "max_inclusive": False, "risk_class": 3},
    {"min": 15, "max": 35, "min_inclusive": True, "max_inclusive": False, "risk_class": 2},
    {"min": 35, "max": None, "min_inclusive": True, "max_inclusive": False, "risk_class": 1},
]


def test_validate_accepts_gap_free_rules():
    validate_reclassification_rules(SLOPE_RULES)  # must not raise


def test_validate_rejects_a_gap():
    rules = [
        {"min": 0, "max": 2, "min_inclusive": True, "max_inclusive": False, "risk_class": 5},
        {"min": 3, "max": None, "min_inclusive": True, "max_inclusive": False, "risk_class": 1},
    ]
    with pytest.raises(ReclassificationError):
        validate_reclassification_rules(rules)


def test_validate_rejects_an_overlap():
    rules = [
        {"min": 0, "max": 5, "min_inclusive": True, "max_inclusive": True, "risk_class": 5},
        {"min": 3, "max": None, "min_inclusive": True, "max_inclusive": False, "risk_class": 1},
    ]
    with pytest.raises(ReclassificationError):
        validate_reclassification_rules(rules)


def test_validate_rejects_shared_inclusive_boundary():
    rules = [
        {"min": 0, "max": 5, "min_inclusive": True, "max_inclusive": True, "risk_class": 5},
        {"min": 5, "max": None, "min_inclusive": True, "max_inclusive": False, "risk_class": 1},
    ]
    with pytest.raises(ReclassificationError):
        validate_reclassification_rules(rules)


def test_validate_rejects_empty_rules():
    with pytest.raises(ReclassificationError):
        validate_reclassification_rules([])


def test_validate_allows_gaps_between_categorical_point_rules():
    # Land-cover class codes 10, 50, 80 aren't a continuum: values 11-49
    # and 51-79 simply never occur, so this must NOT be treated as a
    # coverage gap the way it would for a continuous (range) criterion.
    rules = [
        {"min": 10, "max": 10, "min_inclusive": True, "max_inclusive": True, "risk_class": 1},
        {"min": 50, "max": 50, "min_inclusive": True, "max_inclusive": True, "risk_class": 5},
        {"min": 80, "max": 80, "min_inclusive": True, "max_inclusive": True, "risk_class": 4},
    ]
    validate_reclassification_rules(rules)  # must not raise


def test_validate_rejects_duplicate_categorical_point_rules():
    rules = [
        {"min": 10, "max": 10, "min_inclusive": True, "max_inclusive": True, "risk_class": 1},
        {"min": 10, "max": 10, "min_inclusive": True, "max_inclusive": True, "risk_class": 2},
    ]
    with pytest.raises(ReclassificationError):
        validate_reclassification_rules(rules)


def test_apply_reclassification_maps_values_to_expected_classes():
    values = np.array([[0.5, 3.0, 10.0], [20.0, 50.0, 2.0]], dtype=np.float32)
    out = apply_reclassification(values, SLOPE_RULES, input_nodata=None)
    assert out.tolist() == [[5, 4, 3], [2, 1, 4]]


def test_apply_reclassification_maps_nodata_input_to_reclassified_nodata():
    values = np.array([-9999.0, 1.0], dtype=np.float32)
    out = apply_reclassification(values, SLOPE_RULES, input_nodata=-9999.0)
    assert out[0] == RECLASSIFIED_NODATA
    assert out[1] == 5


def test_apply_reclassification_raises_on_unmatched_value():
    # A criterion whose rules don't extend to negative values.
    rules = [{"min": 0, "max": None, "min_inclusive": True, "max_inclusive": False, "risk_class": 1}]
    values = np.array([-5.0, 1.0], dtype=np.float32)
    with pytest.raises(ReclassificationError):
        apply_reclassification(values, rules, input_nodata=None)


def test_apply_reclassification_categorical_single_value_rules():
    # Land-cover-style rules: min == max, both inclusive, one class code each.
    rules = [
        {"min": 10, "max": 10, "min_inclusive": True, "max_inclusive": True, "risk_class": 1},  # tree cover
        {"min": 50, "max": 50, "min_inclusive": True, "max_inclusive": True, "risk_class": 5},  # built-up
        {"min": 80, "max": 80, "min_inclusive": True, "max_inclusive": True, "risk_class": 4},  # water
    ]
    values = np.array([10, 50, 80], dtype=np.uint8)
    out = apply_reclassification(values, rules, input_nodata=0)
    assert out.tolist() == [1, 5, 4]


# --- rules_fingerprint / apply_reclassification_cached ---


def test_rules_fingerprint_is_stable_regardless_of_rule_order():
    reversed_rules = list(reversed(SLOPE_RULES))
    assert rules_fingerprint(SLOPE_RULES) == rules_fingerprint(reversed_rules)


def test_rules_fingerprint_changes_when_a_threshold_changes():
    changed = [dict(r) for r in SLOPE_RULES]
    changed[0]["max"] = 3  # was 2

    assert rules_fingerprint(SLOPE_RULES) != rules_fingerprint(changed)


def test_rules_fingerprint_changes_when_a_risk_class_changes():
    changed = [dict(r) for r in SLOPE_RULES]
    changed[0]["risk_class"] = 4  # was 5

    assert rules_fingerprint(SLOPE_RULES) != rules_fingerprint(changed)


def test_apply_reclassification_cached_hits_cache_for_same_aoi_and_rules(test_aoi, monkeypatch):
    values = np.array([[0.5, 3.0, 10.0], [20.0, 50.0, 2.0]], dtype=np.float32)
    calls = []

    def tracking_apply(*args, **kwargs):
        calls.append(1)
        return apply_reclassification(*args, **kwargs)

    monkeypatch.setattr("app.data.reclassify.apply_reclassification", tracking_apply)

    first = apply_reclassification_cached("slope", test_aoi, values, SLOPE_RULES, input_nodata=None)
    second = apply_reclassification_cached("slope", test_aoi, values, SLOPE_RULES, input_nodata=None)

    assert np.array_equal(first, second)
    assert len(calls) == 1


def test_apply_reclassification_cached_misses_when_rules_change(test_aoi):
    values = np.array([[0.5, 3.0, 10.0], [20.0, 50.0, 2.0]], dtype=np.float32)
    changed_rules = [dict(r) for r in SLOPE_RULES]
    changed_rules[0] = {**changed_rules[0], "risk_class": 1}  # was 5

    original = apply_reclassification_cached("slope", test_aoi, values, SLOPE_RULES, input_nodata=None)
    updated = apply_reclassification_cached("slope", test_aoi, values, changed_rules, input_nodata=None)

    # Same AOI, same input values, only the rules changed -- a cache keyed
    # only by AOI would incorrectly return `original` here.
    assert original[0, 0] == 5
    assert updated[0, 0] == 1
