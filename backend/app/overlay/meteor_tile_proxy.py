"""Server-side proxy for METEOR's live WMTS flood-hazard tiles
(MapView.jsx's reference overlay).

Why this exists: METEOR's own tile server (maps.meteor-project.org,
MapProxy) sends no `Access-Control-Allow-Origin` header at all
(confirmed live: a plain `curl -I` against a real tile returns no CORS
header of any kind) and a `Referrer-Policy: same-origin` — consistent
with it having only ever been built for same-origin use inside METEOR's
own web map, not third-party embedding. MapLibre GL loads raster tiles
with `crossOrigin` set (it needs the actual pixel bytes for a WebGL
texture, unlike a plain `<img>`, which is why MeteorFloodLegend.jsx's
legend image — a plain `<img src>`, no crossOrigin — was never affected
by this), so every tile request failed as a CORS error in the browser:
confirmed live via a headless-Chrome CDP session showing "TypeError:
Failed to fetch" from inside maplibre-gl's own tile-loading code, even
though the exact same URL succeeded via a server-side `curl`. Real bug,
not a toggle/wiring problem — the toggle and the layer's `visibility`
property were flipping correctly the whole time (see MapView.jsx's own
history), the tiles just never rendered.

Browsers don't apply CORS to server-to-server requests, so proxying
each tile through this backend (same origin as the frontend already
talks to for every other request, already CORS-allowed for it —
app/main.py's CORSMiddleware) sidesteps the problem entirely: this
module fetches the real tile from METEOR over plain HTTPS (no browser
involved) and hands the bytes back to the frontend from an origin it
already trusts.

`flood_type`/`return_period` are validated against the exact catalog
confirmed live via METEOR's own WMTS GetCapabilities (30 real
`ows:Identifier` entries: `{fd,fu,p}-1in{5,10,20,50,75,100,200,250,500,
1000}`) before being interpolated into the upstream URL -- this is a
public-facing proxy endpoint with no auth, so this allow-list is load-
bearing: without it, an unvalidated flood_type/return_period would make
this an open proxy for arbitrary paths under maps.meteor-project.org.
"""

from __future__ import annotations

import httpx

from app.data.errors import DataSourceUnavailableError

from .errors import OverlayValidationError

METEOR_FLOOD_TYPES = ("fd", "fu", "p")
METEOR_FLOOD_RETURN_PERIODS = (5, 10, 20, 50, 75, 100, 200, 250, 500, 1000)

_TILE_URL_TEMPLATE = "https://maps.meteor-project.org/mapproxy/npl-flood/wmts/{layer}/webmercator/{z}/{x}/{y}.png"

# A generous but bounded timeout: METEOR's own MapProxy is usually fast
# (it's serving pre-rendered/pre-cached tiles, not computing anything),
# but this is a live third-party dependency on the request path of an
# interactive map pan/zoom, so it must never hang indefinitely.
_UPSTREAM_TIMEOUT_S = 10.0


class MeteorTileNotFoundError(Exception):
    """The requested z/x/y fell outside METEOR's own tile matrix (the
    upstream responded with a 4xx) -- a normal, routine condition at the
    edges of a raster tile source's zoom/coverage range (every pan/zoom
    requests plenty of tiles beyond the data's real extent; that's just
    how tiled raster layers work), not a service failure. Kept distinct
    from DataSourceUnavailableError specifically so the router maps this
    to a plain 404, not a 503 that would misleadingly suggest METEOR's
    service itself is down and clutter logs for routine boundary tiles.
    """


def fetch_meteor_flood_tile(flood_type: str, return_period: int, z: int, x: int, y: int) -> bytes:
    """Fetch one real tile from METEOR's live WMTS service and return its
    raw PNG bytes.

    Raises OverlayValidationError (-> 422) for a flood_type/return_period
    outside the real catalog; MeteorTileNotFoundError (-> 404) for a
    z/x/y the upstream itself rejects as out of range; DataSourceUnavailableError
    (-> 503) for a genuine upstream failure (network error, timeout, or a
    5xx from METEOR's own server).
    """
    if flood_type not in METEOR_FLOOD_TYPES:
        raise OverlayValidationError(
            f"meteor_flood_tile: unrecognized flood_type {flood_type!r}; must be one of {METEOR_FLOOD_TYPES!r}"
        )
    if return_period not in METEOR_FLOOD_RETURN_PERIODS:
        raise OverlayValidationError(
            f"meteor_flood_tile: unrecognized return_period {return_period!r}; "
            f"must be one of {METEOR_FLOOD_RETURN_PERIODS!r}"
        )

    layer = f"{flood_type}-1in{return_period}"
    url = _TILE_URL_TEMPLATE.format(layer=layer, z=z, x=x, y=y)

    try:
        response = httpx.get(url, timeout=_UPSTREAM_TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise DataSourceUnavailableError(
            f"meteor_flood_tile: upstream request to METEOR's WMTS service failed for "
            f"layer={layer!r} z={z} x={x} y={y}: {exc}"
        ) from exc

    if response.status_code >= 500:
        raise DataSourceUnavailableError(
            f"meteor_flood_tile: upstream returned {response.status_code} for "
            f"layer={layer!r} z={z} x={x} y={y}"
        )
    if response.status_code >= 400:
        raise MeteorTileNotFoundError(
            f"meteor_flood_tile: upstream returned {response.status_code} (tile outside its matrix?) for "
            f"layer={layer!r} z={z} x={x} y={y}"
        )

    return response.content
