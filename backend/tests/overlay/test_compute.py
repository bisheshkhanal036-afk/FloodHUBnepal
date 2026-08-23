"""Unit tests for the pure weighted-sum overlay math (app/overlay/compute.py)
— hand-computable, no file/network I/O.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import box, shape

from app.data.grid import AOIGrid
from app.overlay.compute import (
    RISK_SURFACE_NODATA,
    CriterionRaster,
    RiskSurfaceResult,
    compute_cache_key,
    compute_risk_surface,
    mask_risk_surface_to_polygon,
)
from app.overlay.errors import OverlayValidationError


def _grid(width=2, height=2, origin_x=0.0, origin_y=0.0) -> AOIGrid:
    return AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=origin_x, origin_y=origin_y, width=width, height=height)


def test_hand_computed_weighted_sum_and_fixed_range_normalization():
    # weights 0.5/0.3/0.2 over three all-constant criteria (3, 5, 1):
    # R = 0.5*3 + 0.3*5 + 0.2*1 = 1.5 + 1.5 + 0.2 = 3.2
    # R_norm = (3.2 - 1) / (5 - 1) = 2.2 / 4 = 0.55
    grid = _grid()
    rasters = [
        CriterionRaster("a", np.full((2, 2), 3, dtype=np.uint8), grid),
        CriterionRaster("b", np.full((2, 2), 5, dtype=np.uint8), grid),
        CriterionRaster("c", np.full((2, 2), 1, dtype=np.uint8), grid),
    ]
    weights = {"a": 0.5, "b": 0.3, "c": 0.2}

    result = compute_risk_surface(rasters, weights)

    assert result.risk_surface == pytest.approx(np.full((2, 2), 0.55, dtype=np.float32), abs=1e-6)
    assert result.grid == grid
    assert result.nodata == RISK_SURFACE_NODATA


def test_normalization_uses_the_fixed_1_5_range_not_the_arrays_observed_min_max():
    # All three criteria are constant at class 5 everywhere: R = 5
    # regardless of weights (since weights sum to 1), so R_norm = (5-1)/4
    # = 1.0. A min-max-over-the-array normalization would instead see a
    # completely uniform array and (degenerately) produce 0 everywhere,
    # or be undefined -- this must NOT happen. The fixed-range formula is
    # the only thing that can give 1.0 here.
    grid = _grid()
    rasters = [
        CriterionRaster("a", np.full((2, 2), 5, dtype=np.uint8), grid),
        CriterionRaster("b", np.full((2, 2), 5, dtype=np.uint8), grid),
    ]
    weights = {"a": 0.5, "b": 0.5}

    result = compute_risk_surface(rasters, weights)

    assert result.risk_surface == pytest.approx(np.ones((2, 2), dtype=np.float32), abs=1e-6)


def test_r_is_bounded_in_1_to_5_so_r_norm_is_bounded_in_0_to_1():
    grid = _grid()
    rasters = [
        CriterionRaster("a", np.array([[1, 5], [3, 2]], dtype=np.uint8), grid),
        CriterionRaster("b", np.array([[5, 1], [4, 4]], dtype=np.uint8), grid),
        CriterionRaster("c", np.array([[3, 3], [1, 5]], dtype=np.uint8), grid),
    ]
    weights = {"a": 0.2, "b": 0.5, "c": 0.3}

    result = compute_risk_surface(rasters, weights)

    valid = result.risk_surface[result.risk_surface != RISK_SURFACE_NODATA]
    assert valid.size == 4
    assert np.all(valid >= 0.0) and np.all(valid <= 1.0)


def test_nodata_in_any_one_criterion_propagates_to_risk_surface_nodata():
    grid = _grid()
    a = np.array([[3, 3], [3, 3]], dtype=np.uint8)
    b = np.array([[5, 0], [5, 5]], dtype=np.uint8)  # nodata (0) at (0,1)
    c = np.array([[1, 1], [1, 1]], dtype=np.uint8)
    rasters = [CriterionRaster("a", a, grid), CriterionRaster("b", b, grid), CriterionRaster("c", c, grid)]
    weights = {"a": 0.5, "b": 0.3, "c": 0.2}

    result = compute_risk_surface(rasters, weights)

    assert result.risk_surface[0, 1] == RISK_SURFACE_NODATA
    # every other pixel is unaffected and gets the real computed value.
    expected_elsewhere = 0.5 * 3 + 0.3 * 5 + 0.2 * 1
    expected_elsewhere_norm = (expected_elsewhere - 1) / 4
    assert result.risk_surface[0, 0] == pytest.approx(expected_elsewhere_norm, abs=1e-6)
    assert result.risk_surface[1, 0] == pytest.approx(expected_elsewhere_norm, abs=1e-6)
    assert result.risk_surface[1, 1] == pytest.approx(expected_elsewhere_norm, abs=1e-6)


def test_rejects_weights_not_summing_to_one():
    grid = _grid()
    rasters = [
        CriterionRaster("a", np.full((2, 2), 3, dtype=np.uint8), grid),
        CriterionRaster("b", np.full((2, 2), 3, dtype=np.uint8), grid),
    ]
    weights = {"a": 0.5, "b": 0.3}  # sums to 0.8, not 1

    with pytest.raises(OverlayValidationError, match="sum to 1"):
        compute_risk_surface(rasters, weights)


def test_rejects_criteria_weights_id_mismatch():
    grid = _grid()
    rasters = [
        CriterionRaster("a", np.full((2, 2), 3, dtype=np.uint8), grid),
        CriterionRaster("b", np.full((2, 2), 3, dtype=np.uint8), grid),
    ]
    weights = {"a": 0.5, "c": 0.5}  # "b" has no weight, "c" has no criterion

    with pytest.raises(OverlayValidationError, match="same set of ids"):
        compute_risk_surface(rasters, weights)


def test_rejects_grid_mismatch_even_with_matching_array_shape():
    grid_a = _grid(origin_x=0.0, origin_y=0.0)
    grid_b = _grid(origin_x=1000.0, origin_y=0.0)  # same width/height, different origin
    rasters = [
        CriterionRaster("a", np.full((2, 2), 3, dtype=np.uint8), grid_a),
        CriterionRaster("b", np.full((2, 2), 3, dtype=np.uint8), grid_b),
    ]
    weights = {"a": 0.5, "b": 0.5}

    with pytest.raises(OverlayValidationError, match="grid mismatch"):
        compute_risk_surface(rasters, weights)


def test_rejects_empty_rasters_list():
    with pytest.raises(OverlayValidationError):
        compute_risk_surface([], {})


def test_rejects_duplicate_criterion_id():
    grid = _grid()
    rasters = [
        CriterionRaster("a", np.full((2, 2), 3, dtype=np.uint8), grid),
        CriterionRaster("a", np.full((2, 2), 4, dtype=np.uint8), grid),
    ]
    with pytest.raises(OverlayValidationError, match="duplicate"):
        compute_risk_surface(rasters, {"a": 1.0})


# --- compute_cache_key ---

# A placeholder rules list for tests below that aren't specifically about
# rules-sensitivity (weight/order/polygon behavior) -- rules_fingerprint
# just needs each rule to have a risk_class, nothing about these tests
# cares what the actual thresholds are.
_SAMPLE_RULES = [{"min": None, "max": None, "risk_class": 1}]


def test_cache_key_is_deterministic_and_order_independent():
    from app.data.aoi import AOI

    aoi = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72))
    criteria_set = [
        {"criterion_id": "a", "weight": 0.5, "reclassification_rules": _SAMPLE_RULES},
        {"criterion_id": "b", "weight": 0.5, "reclassification_rules": _SAMPLE_RULES},
    ]
    reordered = [
        {"criterion_id": "b", "weight": 0.5, "reclassification_rules": _SAMPLE_RULES},
        {"criterion_id": "a", "weight": 0.5, "reclassification_rules": _SAMPLE_RULES},
    ]

    assert compute_cache_key(aoi, criteria_set) == compute_cache_key(aoi, reordered)


def test_cache_key_changes_when_weights_change():
    from app.data.aoi import AOI

    aoi = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72))
    criteria_set = [
        {"criterion_id": "a", "weight": 0.5, "reclassification_rules": _SAMPLE_RULES},
        {"criterion_id": "b", "weight": 0.5, "reclassification_rules": _SAMPLE_RULES},
    ]
    different_weights = [
        {"criterion_id": "a", "weight": 0.6, "reclassification_rules": _SAMPLE_RULES},
        {"criterion_id": "b", "weight": 0.4, "reclassification_rules": _SAMPLE_RULES},
    ]

    assert compute_cache_key(aoi, criteria_set) != compute_cache_key(aoi, different_weights)


def test_cache_key_changes_when_reclassification_rules_change_even_with_same_id_and_weight():
    """The regression test for the real bug this covers: two requests for
    the same criterion_id and weight but different reclassification_rules
    (e.g. the frontend's classification editor submitting custom breaks)
    must NOT collide on the same cache_key -- caught live during
    implementation (two manual requests with different breakpoints for
    the same criterion produced an identical cache_key before this fix).
    """
    from app.data.aoi import AOI

    aoi = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72))
    rules_a = [{"min": None, "max": 100, "risk_class": 1}, {"min": 100, "max": None, "risk_class": 5}]
    rules_b = [{"min": None, "max": 200, "risk_class": 1}, {"min": 200, "max": None, "risk_class": 5}]

    criteria_set = [{"criterion_id": "population_density", "weight": 1.0, "reclassification_rules": rules_a}]
    different_rules = [{"criterion_id": "population_density", "weight": 1.0, "reclassification_rules": rules_b}]

    assert compute_cache_key(aoi, criteria_set) != compute_cache_key(aoi, different_rules)


def test_cache_key_matches_schema_pattern():
    import re

    from app.data.aoi import AOI

    aoi = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72))
    key = compute_cache_key(aoi, [{"criterion_id": "a", "weight": 1.0, "reclassification_rules": _SAMPLE_RULES}])
    assert re.fullmatch(r"[a-f0-9]{64}", key)


def test_cache_key_differs_for_a_polygon_aoi_vs_a_plain_bbox_aoi_with_the_same_envelope():
    # A basin selection (polygon set) must never collide in the cache
    # with a hand-drawn AOI that happens to share the same bbox envelope
    # -- since compute_overlay now masks the result to the true polygon
    # shape, those two requests produce genuinely different surfaces.
    from app.data.aoi import AOI

    bbox = (85.30, 27.70, 85.32, 27.72)
    bbox_only = AOI(bbox_4326=bbox)
    triangle = {
        "type": "Polygon",
        "coordinates": [[[85.30, 27.70], [85.32, 27.70], [85.30, 27.72], [85.30, 27.70]]],
    }
    with_polygon = AOI(bbox_4326=bbox, polygon=shape(triangle))

    criteria_set = [{"criterion_id": "a", "weight": 1.0, "reclassification_rules": _SAMPLE_RULES}]
    assert compute_cache_key(bbox_only, criteria_set) != compute_cache_key(with_polygon, criteria_set)


# --- mask_risk_surface_to_polygon ---


def test_mask_sets_pixels_outside_the_polygon_to_nodata_and_leaves_inside_pixels_untouched():
    # 4x4 grid over x:[0,40], y:[0,40] (10m cells); polygon covers only
    # the left half (x in [0,20]) -- so after masking, columns 0-1 must
    # stay 0.5 and columns 2-3 (pixel centers x=25, x=35, outside the
    # polygon) must become nodata, for every row.
    grid = _grid(width=4, height=4, origin_x=0.0, origin_y=40.0)
    surface = np.full((4, 4), 0.5, dtype=np.float32)
    result = RiskSurfaceResult(risk_surface=surface, grid=grid, nodata=RISK_SURFACE_NODATA)
    left_half = box(0, 0, 20, 40)

    masked = mask_risk_surface_to_polygon(result, left_half)

    assert np.all(masked.risk_surface[:, 0:2] == 0.5)
    assert np.all(masked.risk_surface[:, 2:4] == RISK_SURFACE_NODATA)
    assert masked.grid == grid
    assert masked.nodata == RISK_SURFACE_NODATA


def test_mask_with_a_polygon_covering_the_whole_grid_changes_nothing():
    grid = _grid(width=3, height=3, origin_x=0.0, origin_y=30.0)
    surface = np.full((3, 3), 0.8, dtype=np.float32)
    result = RiskSurfaceResult(risk_surface=surface, grid=grid, nodata=RISK_SURFACE_NODATA)
    whole_grid = box(0, 0, 30, 30)

    masked = mask_risk_surface_to_polygon(result, whole_grid)

    assert np.all(masked.risk_surface == 0.8)


def test_mask_with_a_polygon_entirely_outside_the_grid_masks_everything():
    grid = _grid(width=3, height=3, origin_x=0.0, origin_y=30.0)
    surface = np.full((3, 3), 0.8, dtype=np.float32)
    result = RiskSurfaceResult(risk_surface=surface, grid=grid, nodata=RISK_SURFACE_NODATA)
    far_away = box(1000, 1000, 1010, 1010)

    masked = mask_risk_surface_to_polygon(result, far_away)

    assert np.all(masked.risk_surface == RISK_SURFACE_NODATA)
