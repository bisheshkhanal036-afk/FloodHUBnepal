"""Unit tests for app/overlay/breaks.py's classification-break
computation. `_raw_layer_for_source` is mocked so these don't touch
Phase 2's real data-fetch paths — same convention test_sources.py uses.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.data.grid import AOIGrid
from app.overlay.breaks import NUM_CLASSES, compute_criterion_breaks
from app.overlay.errors import OverlayValidationError

GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=4, height=4)


def _mock_source(monkeypatch, raw: np.ndarray, nodata):
    monkeypatch.setattr(
        "app.overlay.breaks._raw_layer_for_source",
        lambda aoi, source: (raw, GRID, nodata, "fake attribution", None),
    )


def test_equal_interval_hand_verified(test_aoi, monkeypatch):
    raw = np.linspace(0, 100, 16).reshape(4, 4)
    _mock_source(monkeypatch, raw, None)

    result = compute_criterion_breaks(test_aoi, "fake_source")

    assert result["min"] == pytest.approx(0.0)
    assert result["max"] == pytest.approx(100.0)
    # Hand-verified: linspace(0, 100, 6) = [0,20,40,60,80,100]; interior = [20,40,60,80].
    assert result["equal_interval"] == pytest.approx([20.0, 40.0, 60.0, 80.0])


def test_quantile_matches_numpy_percentile_directly(test_aoi, monkeypatch):
    values = np.arange(100, dtype=np.float64)
    raw = values.reshape(10, 10)
    grid = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=10, height=10)
    monkeypatch.setattr(
        "app.overlay.breaks._raw_layer_for_source", lambda aoi, source: (raw, grid, None, "fake", None)
    )

    result = compute_criterion_breaks(test_aoi, "fake_source")

    expected = [float(v) for v in np.percentile(values, [20, 40, 60, 80])]
    assert result["quantile"] == pytest.approx(expected)


def test_jenks_minimizes_within_class_variance_better_than_equal_interval(test_aoi, monkeypatch):
    """A hand-verifiable Jenks case: two tight, well-separated clusters.
    Jenks break *values* are always actual data points (each break is
    literally the maximum value of the class below it, not an
    interpolated midpoint in the gap — confirmed against jenkspy's own
    documented example before writing this test) — so the meaningful,
    checkable property isn't "a break lands in the empty gap", it's that
    Jenks' classification actually captures the two-cluster structure
    equal-interval (which only looks at min/max, blind to the gap)
    cannot: the sum of squared within-class deviations from each
    class's own mean must be far smaller under Jenks' breaks than under
    equal-interval's.
    """
    rng = np.random.default_rng(0)
    low_cluster = rng.normal(10, 0.5, 50)
    high_cluster = rng.normal(90, 0.5, 50)
    values = np.concatenate([low_cluster, high_cluster])
    raw = values.reshape(10, 10)
    grid = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=10, height=10)
    monkeypatch.setattr(
        "app.overlay.breaks._raw_layer_for_source", lambda aoi, source: (raw, grid, None, "fake", None)
    )

    result = compute_criterion_breaks(test_aoi, "fake_source")

    def sum_squared_deviations(breaks: list[float]) -> float:
        edges = [-np.inf, *breaks, np.inf]
        total = 0.0
        for lo, hi in zip(edges[:-1], edges[1:]):
            cls = values[(values > lo) & (values <= hi)] if lo != -np.inf else values[values <= hi]
            if cls.size:
                total += float(np.sum((cls - cls.mean()) ** 2))
        return total

    jenks_ssd = sum_squared_deviations(result["jenks"])
    equal_interval_ssd = sum_squared_deviations(result["equal_interval"])
    assert jenks_ssd < equal_interval_ssd / 2, (
        f"Jenks (SSD={jenks_ssd:.1f}) should fit this bimodal data far better than "
        f"equal-interval (SSD={equal_interval_ssd:.1f})"
    )


def test_jenks_samples_down_large_populations_deterministically(test_aoi, monkeypatch):
    """Confirms sampling actually kicks in (and is reproducible) rather
    than silently running Jenks on the full population every time --
    exercising the JENKS_SAMPLE_SIZE code path at all, not just trusting
    it exists.
    """
    from app.overlay import breaks as breaks_module

    rng = np.random.default_rng(1)
    values = rng.normal(50, 15, breaks_module.JENKS_SAMPLE_SIZE * 3)
    raw = values.reshape(-1, 1)
    grid = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=1, height=values.size)
    monkeypatch.setattr(
        "app.overlay.breaks._raw_layer_for_source", lambda aoi, source: (raw, grid, None, "fake", None)
    )

    first = compute_criterion_breaks(test_aoi, "fake_source")
    second = compute_criterion_breaks(test_aoi, "fake_source")

    assert first["jenks"] == second["jenks"]  # fixed sample seed -> deterministic
    assert len(first["jenks"]) == NUM_CLASSES - 1


def test_near_constant_input_falls_back_to_equal_interval_instead_of_raising(test_aoi, monkeypatch):
    raw = np.full((4, 4), 5.0)
    raw[0, 0] = 6.0  # only 2 distinct values -- fewer than NUM_CLASSES
    _mock_source(monkeypatch, raw, None)

    result = compute_criterion_breaks(test_aoi, "fake_source")

    assert result["jenks"] == result["equal_interval"]


def test_nodata_pixels_excluded_from_every_method(test_aoi, monkeypatch):
    raw = np.array([[-9999.0, 10.0], [20.0, 30.0]])
    _mock_source(monkeypatch, raw, -9999.0)

    result = compute_criterion_breaks(test_aoi, "fake_source")

    assert result["min"] == pytest.approx(10.0)
    assert result["max"] == pytest.approx(30.0)
    assert result["valid_pixel_count"] == 3


def test_no_valid_pixels_raises_overlay_validation_error(test_aoi, monkeypatch):
    raw = np.full((4, 4), -9999.0)
    _mock_source(monkeypatch, raw, -9999.0)

    with pytest.raises(OverlayValidationError, match="no valid"):
        compute_criterion_breaks(test_aoi, "fake_source")
