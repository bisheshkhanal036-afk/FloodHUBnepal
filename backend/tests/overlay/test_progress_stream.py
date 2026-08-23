"""Tests for progress_stream.py's SSE event generation -- resolve_
criterion_raster is mocked (same pattern as test_service.py) so these
don't touch Phase 2's real data-fetch paths.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.data.errors import DataSourceUnavailableError
from app.data.grid import AOIGrid
from app.overlay.errors import OverlayValidationError
from app.overlay.progress_stream import stream_compute_events
from app.overlay.service import OverlayCriterionRequest

GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=2, height=2)


def _fake_resolve(monkeypatch, class_value=3):
    def fake(aoi, criterion_id, source, rules):
        return np.full((2, 2), class_value, dtype=np.uint8), GRID, "Fake Source Attribution", None

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake)


def _parse_events(lines: list[str]) -> list[dict]:
    events = []
    for line in lines:
        assert line.startswith("data: ")
        assert line.endswith("\n\n")
        events.append(json.loads(line[len("data: ") : -2]))
    return events


def test_stream_yields_progress_events_then_one_done_event(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    lines = list(stream_compute_events(test_aoi, criteria, {"a": 1.0}, complete=True))
    events = _parse_events(lines)

    assert events[-1]["type"] == "done"
    assert len(events[-1]["result"]["cache_key"]) == 64
    assert events[-1]["result"]["data_url"].startswith("/api/overlay/risk_surface/")
    progress_events = [e for e in events[:-1] if e["type"] == "progress"]
    assert any("a" in e["message"] for e in progress_events)
    assert any("Done" in e["message"] for e in progress_events)
    # Exactly one terminal event -- nothing after "done".
    assert sum(1 for e in events if e["type"] in ("done", "error")) == 1


def test_stream_yields_an_error_event_for_a_known_validation_error(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    # criteria/final_weights mismatch -> OverlayValidationError, raised
    # before on_progress ever fires.
    lines = list(stream_compute_events(test_aoi, criteria, {"different_id": 1.0}, complete=True))
    events = _parse_events(lines)

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert events[0]["error"] == "overlay_validation_error"
    assert "same set of ids" in events[0]["message"]


def test_stream_yields_an_error_event_for_a_data_source_unavailable_error(test_aoi, monkeypatch):
    def failing_resolve(aoi, criterion_id, source, rules):
        raise DataSourceUnavailableError("simulated: no local pbf and R2 not configured")

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", failing_resolve)
    criteria = [OverlayCriterionRequest(id="a", source="dist_to_road", reclassification_rules=[])]

    lines = list(stream_compute_events(test_aoi, criteria, {"a": 1.0}, complete=True))
    events = _parse_events(lines)

    # At least the "Resolving a..." progress message must have fired
    # before the failure, proving this is real mid-computation progress,
    # not just an immediate up-front validation error.
    assert any(e["type"] == "progress" for e in events)
    assert events[-1]["type"] == "error"
    assert events[-1]["error"] == "data_source_unavailable"


def test_stream_yields_an_internal_error_event_for_an_unexpected_exception_not_swallowed(test_aoi, monkeypatch):
    def broken_resolve(aoi, criterion_id, source, rules):
        raise RuntimeError("something genuinely unexpected")

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", broken_resolve)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    lines = list(stream_compute_events(test_aoi, criteria, {"a": 1.0}, complete=True))
    events = _parse_events(lines)

    assert events[-1]["type"] == "error"
    assert events[-1]["error"] == "internal_error"
    assert "something genuinely unexpected" in events[-1]["message"]
