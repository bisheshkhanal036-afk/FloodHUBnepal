"""Tests for POST /api/overlay/compute end to end, via FastAPI's
TestClient. resolve_criterion_raster is mocked so these tests don't
touch Phase 2's real data-fetch paths.
"""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from app.data.grid import AOIGrid
from app.main import app

client = TestClient(app)

GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=2, height=2)


def _fake_resolve(monkeypatch, class_value=3, attribution="Fake Source Attribution", warning=None):
    def fake(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        return np.full((2, 2), class_value, dtype=np.uint8), GRID, attribution, warning

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake)


def _payload(final_weights, complete=True):
    return {
        "aoi": {"bbox": [85.3050, 27.7020, 85.3110, 27.7080]},
        "criteria": [
            {"id": cid, "source": "dem_elevation", "reclassification_rules": [{"min": 0, "max": None, "risk_class": 1}]}
            for cid in final_weights
        ],
        "final_weights": final_weights,
        "complete": complete,
    }


def test_compute_endpoint_returns_risk_surface_metadata(monkeypatch):
    _fake_resolve(monkeypatch, class_value=3, attribution="Fake Source Attribution")

    response = client.post("/api/overlay/compute", json=_payload({"a": 0.5, "b": 0.5}))

    assert response.status_code == 200
    body = response.json()
    assert len(body["cache_key"]) == 64
    assert body["grid"] == {
        "crs": "EPSG:32645", "resolution_m": 10.0, "origin_x": 0.0, "origin_y": 0.0, "width": 2, "height": 2,
    }
    assert body["nodata_value"] == -9999.0
    assert body["value_range"] == [0.0, 1.0]
    assert body["attribution"] == ["Fake Source Attribution"]
    assert body["source_warnings"] == []
    assert body["data_url"] == f"/api/overlay/risk_surface/{body['cache_key']}.tif"


def test_compute_endpoint_surfaces_source_warnings_per_criterion(monkeypatch):
    def fake(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        warning = "computed over a bbox, not a true watershed boundary" if criterion_id == "a" else None
        return np.full((2, 2), 3, dtype=np.uint8), GRID, "Fake Source Attribution", warning

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake)

    response = client.post("/api/overlay/compute", json=_payload({"a": 0.5, "b": 0.5}))

    assert response.status_code == 200
    body = response.json()
    assert body["source_warnings"] == [
        {"criterion_id": "a", "message": "computed over a bbox, not a true watershed boundary"}
    ]
    # attribution stays the plain citation -- the warning is never folded into it.
    assert body["attribution"] == ["Fake Source Attribution"]


def test_compute_endpoint_rejects_aoi_exceeding_area_cap(monkeypatch):
    _fake_resolve(monkeypatch)
    payload = _payload({"a": 1.0})
    payload["aoi"] = {"bbox": [85.0, 27.0, 85.5, 27.5]}  # ~2,500+ km^2, well over the 1000 km^2 cap

    response = client.post("/api/overlay/compute", json=payload)

    assert response.status_code == 422


def test_compute_endpoint_rejects_incomplete_weights(monkeypatch):
    _fake_resolve(monkeypatch)

    response = client.post("/api/overlay/compute", json=_payload({"a": 1.0}, complete=False))

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "overlay_validation_error"


def test_compute_endpoint_rejects_criteria_weights_mismatch(monkeypatch):
    _fake_resolve(monkeypatch)
    payload = _payload({"a": 1.0})
    payload["final_weights"] = {"a": 0.5, "different_id": 0.5}

    response = client.post("/api/overlay/compute", json=payload)

    assert response.status_code == 422


def test_compute_endpoint_rejects_unrecognized_source(monkeypatch):
    payload = _payload({"a": 1.0})
    payload["criteria"][0]["source"] = "not_a_real_source"

    response = client.post("/api/overlay/compute", json=payload)

    assert response.status_code == 422


# --- POST /api/overlay/compute/stream ---


def _parse_sse_body(text):
    import json

    events = []
    for block in text.strip().split("\n\n"):
        if not block:
            continue
        assert block.startswith("data: ")
        events.append(json.loads(block[len("data: ") :]))
    return events


def test_compute_stream_endpoint_returns_sse_content_type_and_a_done_event(monkeypatch):
    _fake_resolve(monkeypatch)

    response = client.post("/api/overlay/compute/stream", json=_payload({"a": 1.0}))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_body(response.text)
    assert events[-1]["type"] == "done"
    assert len(events[-1]["result"]["cache_key"]) == 64
    assert any(e["type"] == "progress" for e in events)


def test_compute_stream_endpoint_returns_an_error_event_not_an_http_error_status(monkeypatch):
    """An SSE response's HTTP status is always 200 by the time streaming
    starts -- a request-level problem (here, an unrecognized source)
    still comes back as HTTP 200 with an in-band "error" event, unlike
    POST /compute's own 422 for the exact same bad payload.
    """
    payload = _payload({"a": 1.0})
    payload["criteria"][0]["source"] = "not_a_real_source"

    response = client.post("/api/overlay/compute/stream", json=payload)

    assert response.status_code == 200
    events = _parse_sse_body(response.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["error"] == "overlay_validation_error"


# --- GET /api/overlay/risk_surface/{cache_key}.tif ---


def test_risk_surface_file_route_serves_the_geotiff_after_a_successful_compute(monkeypatch):
    _fake_resolve(monkeypatch)
    compute_response = client.post("/api/overlay/compute", json=_payload({"a": 1.0}))
    data_url = compute_response.json()["data_url"]

    file_response = client.get(data_url)

    assert file_response.status_code == 200
    assert file_response.headers["content-type"] == "image/tiff"
    assert file_response.content[:2] in (b"II", b"MM")  # TIFF byte-order marker


def test_risk_surface_file_route_404s_for_a_cache_key_that_was_never_computed():
    response = client.get("/api/overlay/risk_surface/" + "a" * 64 + ".tif")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "risk_surface_not_found"


def test_risk_surface_file_route_422s_for_a_malformed_cache_key():
    response = client.get("/api/overlay/risk_surface/not-a-valid-hash.tif")
    assert response.status_code == 422


# --- POST /api/overlay/criteria/breaks ---


def _breaks_payload(source="dem_elevation"):
    return {"aoi": {"bbox": [85.3050, 27.7020, 85.3110, 27.7080]}, "source": source}


def test_criteria_breaks_endpoint_returns_all_three_methods(monkeypatch):
    # app/overlay/__init__.py re-exports `router` (the APIRouter
    # instance) at the package level, which shadows the `app.overlay.
    # router` *submodule* for monkeypatch's string-path attribute
    # traversal -- importing the submodule object directly sidesteps
    # that collision.
    import sys
    overlay_router_module = sys.modules["app.overlay.router"]

    monkeypatch.setattr(
        overlay_router_module,
        "compute_criterion_breaks",
        lambda aoi, source, stream_threshold_cells=None: {
            "min": 1300.0,
            "max": 1600.0,
            "valid_pixel_count": 42,
            "equal_interval": [1360.0, 1420.0, 1480.0, 1540.0],
            "quantile": [1350.0, 1400.0, 1450.0, 1500.0],
            "jenks": [1355.0, 1410.0, 1470.0, 1530.0],
        },
    )

    response = client.post("/api/overlay/criteria/breaks", json=_breaks_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["min"] == 1300.0
    assert body["max"] == 1600.0
    assert body["valid_pixel_count"] == 42
    assert len(body["equal_interval"]) == 4
    assert len(body["quantile"]) == 4
    assert len(body["jenks"]) == 4


def test_criteria_breaks_endpoint_rejects_unrecognized_source():
    response = client.post("/api/overlay/criteria/breaks", json=_breaks_payload(source="not_a_real_source"))

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "overlay_validation_error"


def test_criteria_breaks_endpoint_rejects_aoi_exceeding_area_cap():
    payload = _breaks_payload()
    payload["aoi"] = {"bbox": [85.0, 27.0, 85.5, 27.5]}  # ~2,500+ km^2, well over the 1000 km^2 cap

    response = client.post("/api/overlay/criteria/breaks", json=payload)

    assert response.status_code == 422


def test_criteria_breaks_endpoint_surfaces_data_source_unavailable_as_503(monkeypatch):
    import sys
    overlay_router_module = sys.modules["app.overlay.router"]
    from app.data.errors import DataSourceUnavailableError

    def fake(aoi, source, stream_threshold_cells=None):
        raise DataSourceUnavailableError("simulated: no local pbf and R2 not configured")

    monkeypatch.setattr(overlay_router_module, "compute_criterion_breaks", fake)

    response = client.post("/api/overlay/criteria/breaks", json=_breaks_payload(source="dist_to_road"))

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "data_source_unavailable"
