from __future__ import annotations

import numpy as np
import pytest

from app.overlay.compute import RISK_SURFACE_NODATA
from app.overlay.hazard_classes import (
    HAZARD_CLASS_LABELS,
    HAZARD_CLASS_NODATA,
    risk_surface_to_hazard_classes,
)


def test_known_r_norm_values_bucket_to_the_expected_class():
    # R_norm = (R-1)/4 for R in {1,2,3,4,5} lands exactly on {0, 0.25, 0.5, 0.75, 1.0}.
    r_norm = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float32)

    classes = risk_surface_to_hazard_classes(r_norm, RISK_SURFACE_NODATA)

    assert classes.tolist() == [1, 2, 3, 4, 5]


def test_round_nearest_not_floor():
    # R_norm=0.99 -> R=4.96 -> nearest class 5, NOT floor's class 4. This is
    # the exact case this module's own docstring cites as floor's failure mode.
    r_norm = np.array([0.99], dtype=np.float32)

    classes = risk_surface_to_hazard_classes(r_norm, RISK_SURFACE_NODATA)

    assert classes[0] == 5


def test_midpoint_values_round_to_the_nearer_class_boundary():
    # R=1.5 (R_norm=0.125) is exactly halfway between class 1 and 2 --
    # numpy's round-half-to-even sends .5 to the nearest EVEN integer, so
    # this documents the actual tie-break behavior rather than assuming
    # "round half up".
    r_norm = np.array([0.125], dtype=np.float32)  # R = 0.125*4+1 = 1.5

    classes = risk_surface_to_hazard_classes(r_norm, RISK_SURFACE_NODATA)

    assert classes[0] == 2  # round-half-to-even: 1.5 -> 2


def test_nodata_pixels_map_to_hazard_class_nodata_not_a_real_class():
    r_norm = np.array([0.5, RISK_SURFACE_NODATA], dtype=np.float32)

    classes = risk_surface_to_hazard_classes(r_norm, RISK_SURFACE_NODATA)

    assert classes.tolist() == [3, HAZARD_CLASS_NODATA]


def test_output_is_clamped_to_1_5_even_given_out_of_spec_input():
    # Defensive: real risk_surface values are always in [0,1] by
    # construction (compute_risk_surface's own convex-combination
    # guarantee), but this function shouldn't silently produce a class
    # outside 1-5 if it were ever handed something slightly out of range.
    r_norm = np.array([-0.1, 1.1], dtype=np.float32)

    classes = risk_surface_to_hazard_classes(r_norm, RISK_SURFACE_NODATA)

    assert classes.tolist() == [1, 5]


def test_output_dtype_is_uint8():
    r_norm = np.array([0.5], dtype=np.float32)
    assert risk_surface_to_hazard_classes(r_norm, RISK_SURFACE_NODATA).dtype == np.uint8


def test_all_5_labels_are_defined():
    assert set(HAZARD_CLASS_LABELS.keys()) == {1, 2, 3, 4, 5}
    assert HAZARD_CLASS_LABELS[1] == "Very Low"
    assert HAZARD_CLASS_LABELS[5] == "Very High"


@pytest.mark.parametrize("nodata", [-9999.0, -1.0])
def test_works_with_a_different_nodata_value_than_the_module_default(nodata):
    # The function takes nodata as a parameter rather than hardcoding
    # RISK_SURFACE_NODATA -- confirm it actually uses the one it's given.
    r_norm = np.array([0.5, nodata], dtype=np.float32)

    classes = risk_surface_to_hazard_classes(r_norm, nodata)

    assert classes.tolist() == [3, HAZARD_CLASS_NODATA]
