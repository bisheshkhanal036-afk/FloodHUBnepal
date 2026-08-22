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
    def fake(aoi, criterion_id, source, rules):
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


def test_source_warnings_are_collected_per_criterion(test_aoi, monkeypatch):
    """A source that flags a warning (e.g. hydrology.py's twi/
    drainage_density on a plain bbox AOI) must surface it on
    OverlayResult.source_warnings, tagged with the criterion id it
    belongs to -- distinct from (and never folded into) `attribution`.
    """
    calls = []

    def fake(aoi, criterion_id, source, rules):
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
