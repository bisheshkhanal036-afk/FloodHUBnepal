"""Tests for app/overlay/meteor_tile_proxy.py -- the server-side proxy
for METEOR's live WMTS flood-hazard tiles. httpx.get is mocked so these
tests never touch the real network; test_router.py's own
test_meteor_flood_tile_endpoint_* tests cover the FastAPI route wrapping
this module.
"""

from __future__ import annotations

import httpx
import pytest

from app.data.errors import DataSourceUnavailableError
from app.overlay.errors import OverlayValidationError
from app.overlay.meteor_tile_proxy import (
    MeteorTileNotFoundError,
    fetch_meteor_flood_tile,
)


class _FakeResponse:
    def __init__(self, status_code=200, content=b"fake-png-bytes"):
        self.status_code = status_code
        self.content = content


def test_fetches_the_real_tile_bytes_for_a_valid_request(monkeypatch):
    seen_url = {}

    def fake_get(url, timeout=None):
        seen_url["url"] = url
        return _FakeResponse(200, b"real-tile-bytes")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = fetch_meteor_flood_tile("fd", 100, 12, 3018, 1719)

    assert result == b"real-tile-bytes"
    # Layer id convention is "{type}-1in{years}" -- see this module's own
    # docstring / MapView.jsx's meteorFloodTiles for the real bug this
    # guards against (the WMTS server 400s on "fd-100").
    assert seen_url["url"] == (
        "https://maps.meteor-project.org/mapproxy/npl-flood/wmts/fd-1in100/webmercator/12/3018/1719.png"
    )


@pytest.mark.parametrize("bad_type", ["FD", "fluvial", "", "fd-1in100", "../../etc/passwd"])
def test_rejects_a_flood_type_outside_the_real_catalog(bad_type):
    with pytest.raises(OverlayValidationError, match="flood_type"):
        fetch_meteor_flood_tile(bad_type, 100, 12, 3018, 1719)


@pytest.mark.parametrize("bad_period", [0, 1, 15, 999, -100, 100000])
def test_rejects_a_return_period_outside_the_real_catalog(bad_period):
    with pytest.raises(OverlayValidationError, match="return_period"):
        fetch_meteor_flood_tile("fd", bad_period, 12, 3018, 1719)


def test_validation_happens_before_any_network_call(monkeypatch):
    """A bad flood_type/return_period must never even reach httpx.get --
    this is a public, unauthenticated proxy endpoint, so the allow-list
    check is load-bearing (an unvalidated value reaching the URL would
    make this an open proxy for arbitrary paths under
    maps.meteor-project.org), not just an early-exit optimization.
    """
    called = []
    monkeypatch.setattr(httpx, "get", lambda *a, **k: called.append(1))

    with pytest.raises(OverlayValidationError):
        fetch_meteor_flood_tile("not-a-real-type", 100, 12, 3018, 1719)

    assert called == []


def test_upstream_4xx_raises_tile_not_found_not_unavailable(monkeypatch):
    """A z/x/y outside METEOR's own tile matrix is routine (every pan/
    zoom requests plenty of tiles beyond real data extent) -- must map
    to MeteorTileNotFoundError (-> 404), not DataSourceUnavailableError
    (-> 503, which would misleadingly suggest METEOR's whole service is
    down for what is actually a normal boundary condition).
    """
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: _FakeResponse(400))

    with pytest.raises(MeteorTileNotFoundError):
        fetch_meteor_flood_tile("fd", 100, 30, 999999999, 999999999)


def test_upstream_5xx_raises_data_source_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: _FakeResponse(502))

    with pytest.raises(DataSourceUnavailableError):
        fetch_meteor_flood_tile("fd", 100, 12, 3018, 1719)


def test_network_failure_raises_data_source_unavailable(monkeypatch):
    def raising_get(url, timeout=None):
        raise httpx.ConnectTimeout("simulated timeout")

    monkeypatch.setattr(httpx, "get", raising_get)

    with pytest.raises(DataSourceUnavailableError):
        fetch_meteor_flood_tile("fd", 100, 12, 3018, 1719)


@pytest.mark.parametrize("flood_type", ["fd", "fu", "p"])
@pytest.mark.parametrize("years", [5, 10, 20, 50, 75, 100, 200, 250, 500, 1000])
def test_every_real_catalog_combination_is_accepted(monkeypatch, flood_type, years):
    """The full 3x10 = 30-layer catalog confirmed live against METEOR's
    own WMTS GetCapabilities document -- every real combination must be
    accepted, not just the default fd/100.
    """
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: _FakeResponse(200, b"ok"))
    assert fetch_meteor_flood_tile(flood_type, years, 10, 100, 100) == b"ok"
