"""Tests for the orchestration pipeline (app/overlay/service.py):
resolve -> combine -> cache -> materialize. resolve_criterion_raster is
mocked here so these tests don't touch Phase 2's real data-fetch paths —
that's covered separately by test_integration.py.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.data.grid import AOIGrid
from app.overlay.compute import RISK_SURFACE_NODATA
from app.overlay.errors import OverlayValidationError
from app.overlay.service import OverlayCriterionRequest, compute_overlay

GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=2, height=2)


def _fake_resolve(monkeypatch, calls, class_value=3, attribution="Fake Source Attribution", warning=None):
    def fake(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        calls.append((criterion_id, source))
        return np.full((2, 2), class_value, dtype=np.uint8), GRID, attribution, warning

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake)


def test_rejects_incomplete_weights_without_fetching_any_data(test_aoi, monkeypatch):
    calls = []
    _fake_resolve(monkeypatch, calls)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    with pytest.raises(OverlayValidationError, match="incomplete"):
        compute_overlay(test_aoi, criteria, {"a": 1.0}, complete=False)

    assert calls == []  # rejected before any Phase 2 fetch was attempted


def test_rejects_criteria_weights_mismatch_without_fetching_any_data(test_aoi, monkeypatch):
    calls = []
    _fake_resolve(monkeypatch, calls)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    with pytest.raises(OverlayValidationError, match="same set of ids"):
        compute_overlay(test_aoi, criteria, {"a": 0.5, "b": 0.5}, complete=True)

    assert calls == []


def test_successful_compute_returns_cache_key_grid_and_attribution(test_aoi, monkeypatch):
    calls = []
    _fake_resolve(monkeypatch, calls, class_value=3, attribution="Fake Source Attribution")
    criteria = [
        OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[]),
        OverlayCriterionRequest(id="b", source="worldcover_land_cover", reclassification_rules=[]),
    ]

    result = compute_overlay(test_aoi, criteria, {"a": 0.5, "b": 0.5}, complete=True)

    assert len(result.cache_key) == 64
    assert result.risk_surface.grid == GRID
    assert result.attribution == ["Fake Source Attribution"]  # deduplicated
    assert result.source_warnings == []  # nothing to flag by default
    assert result.risk_surface.risk_surface == pytest.approx(np.full((2, 2), 0.5, dtype=np.float32), abs=1e-6)
    assert Path(result.data_url).exists()


def test_overlay_result_carries_each_criterions_own_raster_unmasked(test_aoi, monkeypatch):
    """OverlayResult.criterion_rasters -- the field report.py's per-
    criterion snapshot feature depends on -- must carry every requested
    criterion's own already-reclassified raster (not just the combined
    surface), matching the criteria list, and must NOT be polygon-masked
    here (report.py applies its own masking when materializing a
    snapshot; POST /compute itself never reads this field at all, so it
    would be pointless work to mask it in service.py).
    """
    calls = []
    _fake_resolve(monkeypatch, calls, class_value=3)
    criteria = [
        OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[]),
        OverlayCriterionRequest(id="b", source="worldcover_land_cover", reclassification_rules=[]),
    ]

    result = compute_overlay(test_aoi, criteria, {"a": 0.5, "b": 0.5}, complete=True)

    assert [r.criterion_id for r in result.criterion_rasters] == ["a", "b"]
    for r in result.criterion_rasters:
        assert r.grid == GRID
        assert (r.reclassified == 3).all()


def test_on_progress_is_called_for_each_criterion_and_at_the_end(test_aoi, monkeypatch):
    calls = []
    _fake_resolve(monkeypatch, calls)
    criteria = [
        OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[]),
        OverlayCriterionRequest(id="b", source="dem_slope", reclassification_rules=[]),
    ]
    messages = []

    compute_overlay(test_aoi, criteria, {"a": 0.5, "b": 0.5}, complete=True, on_progress=messages.append)

    assert any("a" in m and "1/2" in m for m in messages)
    assert any("b" in m and "2/2" in m for m in messages)
    assert any("Combining 2 criteria" in m for m in messages)
    assert messages[-1] == "Done."


def test_on_progress_defaults_to_none_and_is_never_required(test_aoi, monkeypatch):
    """Every existing caller (report.py included) doesn't pass on_progress
    at all -- must behave identically to before this parameter existed.
    """
    calls = []
    _fake_resolve(monkeypatch, calls)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    result = compute_overlay(test_aoi, criteria, {"a": 1.0}, complete=True)  # no on_progress

    assert len(result.cache_key) == 64


def test_on_progress_mentions_masking_only_for_a_polygon_aoi(monkeypatch):
    calls = []
    _fake_resolve(monkeypatch, calls)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    from shapely.geometry import shape

    bbox = (85.30, 27.70, 85.32, 27.72)
    triangle = {"type": "Polygon", "coordinates": [[[85.30, 27.70], [85.32, 27.70], [85.30, 27.72], [85.30, 27.70]]]}
    from app.data.aoi import AOI

    with_polygon = AOI(bbox_4326=bbox, polygon=shape(triangle))
    bbox_only = AOI(bbox_4326=bbox)

    messages_with_polygon = []
    compute_overlay(with_polygon, criteria, {"a": 1.0}, complete=True, on_progress=messages_with_polygon.append)
    messages_bbox_only = []
    compute_overlay(bbox_only, criteria, {"a": 1.0}, complete=True, on_progress=messages_bbox_only.append)

    assert any("Masking" in m for m in messages_with_polygon)
    assert not any("Masking" in m for m in messages_bbox_only)


def test_on_progress_skips_per_criterion_messages_on_a_full_cache_hit(test_aoi, monkeypatch):
    calls = []
    _fake_resolve(monkeypatch, calls)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]
    compute_overlay(test_aoi, criteria, {"a": 1.0}, complete=True)  # warm the cache, no on_progress needed

    messages = []
    compute_overlay(test_aoi, criteria, {"a": 1.0}, complete=True, on_progress=messages.append)

    assert not any("Resolving" in m for m in messages)  # _compute() never ran the second time
    assert messages[0] == "Checking cache…"
    assert messages[-1] == "Done."


def test_source_warnings_are_collected_per_criterion(test_aoi, monkeypatch):
    """A source that flags a warning (e.g. hydrology.py's twi/
    drainage_density on a plain bbox AOI) must surface it on
    OverlayResult.source_warnings, tagged with the criterion id it
    belongs to -- distinct from (and never folded into) `attribution`.
    """
    calls = []

    def fake(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        calls.append((criterion_id, source))
        warning = "edge reliability warning" if criterion_id == "b" else None
        return np.full((2, 2), 3, dtype=np.uint8), GRID, "Fake Source Attribution", warning

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake)
    criteria = [
        OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[]),
        OverlayCriterionRequest(id="b", source="twi", reclassification_rules=[]),
    ]

    result = compute_overlay(test_aoi, criteria, {"a": 0.5, "b": 0.5}, complete=True)

    assert len(result.source_warnings) == 1
    assert result.source_warnings[0].criterion_id == "b"
    assert result.source_warnings[0].message == "edge reliability warning"
    # attribution is unaffected -- still just the plain citation, never
    # the warning text folded into it.
    assert result.attribution == ["Fake Source Attribution"]


def test_second_call_with_same_aoi_criteria_weights_hits_cache(test_aoi, monkeypatch):
    calls = []
    _fake_resolve(monkeypatch, calls)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    first = compute_overlay(test_aoi, criteria, {"a": 1.0}, complete=True)
    second = compute_overlay(test_aoi, criteria, {"a": 1.0}, complete=True)

    assert first.cache_key == second.cache_key
    assert len(calls) == 1  # resolve_criterion_raster only ran once


def test_different_weights_for_same_aoi_and_criteria_gives_different_cache_key_and_recomputes(test_aoi, monkeypatch):
    calls = []
    _fake_resolve(monkeypatch, calls)
    criteria = [
        OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[]),
        OverlayCriterionRequest(id="b", source="dem_slope", reclassification_rules=[]),
    ]

    first = compute_overlay(test_aoi, criteria, {"a": 0.5, "b": 0.5}, complete=True)
    second = compute_overlay(test_aoi, criteria, {"a": 0.7, "b": 0.3}, complete=True)

    assert first.cache_key != second.cache_key
    assert len(calls) == 4  # 2 criteria resolved fresh for each of the 2 distinct weight sets


def test_different_reclassification_rules_for_same_id_and_weight_gives_different_cache_key_and_recomputes(
    test_aoi, monkeypatch
):
    """The regression test for the real bug this covers, at the full
    compute_overlay level (not just compute_cache_key's hash) -- proves
    both halves of the fix: a different cache_key, AND an actually
    different materialized result, not a stale one silently reused from
    the first request. The fake resolver below deliberately responds to
    `rules` (unlike this file's other tests' _fake_resolve, which ignores
    it) specifically so this test can tell the two calls' outputs apart.
    """
    calls = []

    def fake(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        calls.append((criterion_id, rules))
        # A trivial "respond to the rules" stand-in for real reclassification:
        # different rules -> different risk class.
        class_value = 5 if rules and rules[0].get("risk_class") == 5 else 3
        return np.full((2, 2), class_value, dtype=np.uint8), GRID, "Fake Source Attribution", None

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake)
    rules_a = [{"min": None, "max": None, "risk_class": 3}]
    rules_b = [{"min": None, "max": None, "risk_class": 5}]

    first = compute_overlay(
        test_aoi, [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=rules_a)],
        {"a": 1.0}, complete=True,
    )
    second = compute_overlay(
        test_aoi, [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=rules_b)],
        {"a": 1.0}, complete=True,
    )

    assert first.cache_key != second.cache_key
    assert len(calls) == 2  # resolved fresh for each of the 2 distinct rule sets, not a stale cache hit
    assert not np.array_equal(first.risk_surface.risk_surface, second.risk_surface.risk_surface)
    assert np.all(first.risk_surface.risk_surface == pytest.approx(0.5, abs=1e-6))  # class 3 -> (3-1)/(5-1)
    assert np.all(second.risk_surface.risk_surface == pytest.approx(1.0, abs=1e-6))  # class 5 -> (5-1)/(5-1)


def test_geotiff_is_rewritten_if_missing_even_on_a_cache_hit(test_aoi, monkeypatch):
    calls = []
    _fake_resolve(monkeypatch, calls)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    first = compute_overlay(test_aoi, criteria, {"a": 1.0}, complete=True)
    Path(first.data_url).unlink()  # simulate the GeoTIFF having gone missing
    assert not Path(first.data_url).exists()

    second = compute_overlay(test_aoi, criteria, {"a": 1.0}, complete=True)

    assert len(calls) == 1  # array computation was still a cache hit
    assert Path(second.data_url).exists()  # but the file was rematerialized


# --- true-polygon-shape masking (basin selections) ---


def test_a_polygon_aoi_gets_masked_to_its_true_shape(monkeypatch):
    """A basin selection (AOI.polygon set) must have its result run
    through mask_risk_surface_to_polygon, and the RETURNED result must
    actually be what masking produced -- not just call it and discard
    the output. The masking math itself is covered separately and
    hand-verified in test_compute.py; this only checks the orchestration
    wiring, same spirit as this file's existing mocked-resolve tests.
    """
    from app.data.aoi import AOI
    from app.overlay.compute import RiskSurfaceResult

    calls = []
    _fake_resolve(monkeypatch, calls)
    sentinel = RiskSurfaceResult(risk_surface=np.zeros((1, 1), dtype=np.float32), grid=GRID, nodata=RISK_SURFACE_NODATA)
    mask_calls = []

    def fake_mask(result, polygon_utm):
        mask_calls.append((result, polygon_utm))
        return sentinel

    monkeypatch.setattr("app.overlay.service.mask_risk_surface_to_polygon", fake_mask)

    from shapely.geometry import box as shapely_box

    polygon_aoi = AOI(bbox_4326=(85.30, 27.70, 85.32, 27.72), polygon=shapely_box(85.30, 27.70, 85.32, 27.72))
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    result = compute_overlay(polygon_aoi, criteria, {"a": 1.0}, complete=True)

    assert len(mask_calls) == 1
    assert result.risk_surface is sentinel


def test_a_plain_bbox_aoi_never_gets_masked(test_aoi, monkeypatch):
    calls = []
    _fake_resolve(monkeypatch, calls)

    def fail_if_called(result, polygon_utm):
        raise AssertionError("mask_risk_surface_to_polygon must not run for a bbox-only AOI")

    monkeypatch.setattr("app.overlay.service.mask_risk_surface_to_polygon", fail_if_called)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    assert test_aoi.polygon is None
    compute_overlay(test_aoi, criteria, {"a": 1.0}, complete=True)  # must not raise
