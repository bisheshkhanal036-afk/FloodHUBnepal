"""Supporting evidence for a Citizen Mode assessment.

WHY THIS EXISTS
===============
The first version of Citizen Mode returned a risk level and two or three
generic sentences ("the ground is very flat here"). That is a correct
summary and a weak argument. Somebody deciding whether to buy land needs
to know *why* the answer is what it is, in terms they can check against
the place itself.

This module supplies the checkable parts:

  * **Flood history** -- actual recorded floods near the point, with
    dates. Independently verifiable by anyone who lives there, and by
    far the strongest reason to believe (or disbelieve) the model.
  * **Percentile ranking** -- what "HIGH" means relative to the rest of
    the valley, so the label is calibrated rather than absolute.
  * **Named nearest river** -- concrete orientation instead of "a
    channel".

--- An honesty constraint on the river distance ---

Distance-to-river is offered here as CONTEXT ONLY, never as a reason for
the score, and `river_is_not_a_reason` exists to make that explicit to
the caller.

This project's own validation measured `dist_to_river` at **AUC 0.24
against real flood records -- worse than random**. Observed flood points
in this valley sit a median 620 m from a river against a valley-wide
median of 583 m; if anything, reported flooding here is slightly
*farther* from rivers than average, because it is largely drainage
failure rather than channel overtopping. That is why the criterion is
excluded from the scoring profile entirely (see profile.py).

Telling a user "this is high risk because you are near a river" would be
the intuitive thing to say and would contradict our own evidence.
Showing them which river is nearby, while being clear that proximity is
not what drove the score, is both more honest and more informative --
the counterintuitive finding is itself worth telling them.
"""

from __future__ import annotations

import functools
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

RESOURCES = Path(__file__).resolve().parent / "resources"
FLOOD_INVENTORY_PATH = RESOURCES / "ktm_flood_inventory.json"
WATERWAYS_PATH = RESOURCES / "ktm_named_waterways.geojson"

# Radius searched for past flood records. 2 km is a compromise: tight
# enough that a hit is plausibly relevant to this location, wide enough
# to find something given BIPAD records are often placed at a ward or
# settlement centroid rather than the exact inundated spot.
FLOOD_HISTORY_RADIUS_M = 2000.0

# Beyond this, naming the "nearest" river is more misleading than
# helpful -- it is not a feature of this location any more.
MAX_RIVER_DISTANCE_M = 3000.0

_EARTH_R = 6371000.0


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in metres.

    Used rather than reprojecting because these are one-off point
    distances at valley scale, where the error against a projected
    calculation is far below the positional accuracy of the underlying
    records themselves.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


@dataclass
class FloodRecord:
    date: str
    distance_m: int
    hazard: str
    place: str | None


@dataclass
class NearestRiver:
    name: str
    distance_m: int
    # Always True in this valley -- see the module docstring. Carried
    # explicitly so the UI cannot accidentally present the river as the
    # cause of the score.
    river_is_not_a_reason: bool = True


@functools.lru_cache(maxsize=1)
def _flood_inventory() -> list[dict]:
    """Recorded flood/inundation incidents, from BIPAD (NDRRMA).

    Shipped as a package resource rather than left under
    backend/data/raw/ (which is gitignored) because it is 25 KB of
    public government data that this feature depends on, and harvesting
    it fresh means paginating ~62,000 incidents. Regenerate with
    backend/scripts/harvest_bipad_inventory.py.
    """
    if not FLOOD_INVENTORY_PATH.exists():
        logger.warning("citizen: flood inventory missing at %s; history disabled", FLOOD_INVENTORY_PATH)
        return []
    return json.loads(FLOOD_INVENTORY_PATH.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _waterways():
    """Named waterways in the pilot area, as (name, coords array) pairs.

    Geometry is flattened to plain coordinate arrays at load time so the
    per-request distance check is pure numpy and needs no geospatial
    library on the request path.
    """
    if not WATERWAYS_PATH.exists():
        logger.warning("citizen: waterways missing at %s; river context disabled", WATERWAYS_PATH)
        return []

    data = json.loads(WATERWAYS_PATH.read_text(encoding="utf-8"))
    out: list[tuple[str, np.ndarray]] = []
    for feat in data.get("features", []):
        name = (feat.get("properties") or {}).get("name")
        geom = feat.get("geometry") or {}
        if not name:
            continue
        if geom.get("type") == "LineString":
            parts = [geom["coordinates"]]
        elif geom.get("type") == "MultiLineString":
            parts = geom["coordinates"]
        else:
            continue
        for coords in parts:
            arr = np.asarray(coords, dtype=np.float64)
            if arr.ndim == 2 and len(arr) > 0:
                out.append((str(name), arr[:, :2]))
    return out


def nearby_flood_history(lon: float, lat: float,
                         radius_m: float = FLOOD_HISTORY_RADIUS_M) -> list[FloodRecord]:
    """Recorded floods near this point, nearest first.

    Deliberately returns the raw records rather than a verdict. "Three
    floods within 1.2 km, in 2018 and twice in 2024" is something a
    resident can check against their own memory; a derived score is not.
    """
    records: list[FloodRecord] = []
    for p in _flood_inventory():
        d = _haversine_m(lon, lat, p["lon"], p["lat"])
        if d <= radius_m:
            records.append(FloodRecord(
                date=p.get("date") or "",
                distance_m=int(round(d)),
                hazard=p.get("hazard") or "Flood",
                place=p.get("title"),
            ))
    records.sort(key=lambda r: r.distance_m)
    return records


def nearest_named_river(lon: float, lat: float) -> NearestRiver | None:
    """The closest named waterway, or None if none is close enough.

    Distance is to the nearest *vertex* of the line, not to the nearest
    point on its segments. At the ~10-30 m vertex spacing of OSM river
    geometry this is accurate to well within the precision we report
    (rounded to 10 m), and it keeps the calculation to one vectorised
    numpy pass per feature.
    """
    best_name, best_d = None, float("inf")
    for name, coords in _waterways():
        dlon = np.radians(coords[:, 0] - lon)
        p1 = math.radians(lat)
        p2 = np.radians(coords[:, 1])
        a = np.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
        d = float((2 * _EARTH_R * np.arcsin(np.sqrt(a))).min())
        if d < best_d:
            best_name, best_d = name, d

    if best_name is None or best_d > MAX_RIVER_DISTANCE_M:
        return None
    return NearestRiver(name=best_name, distance_m=int(round(best_d / 10.0) * 10))


def percentile_of(value: float, sorted_sample: np.ndarray) -> int:
    """Where `value` sits in `sorted_sample`, as a 0-100 percentile.

    Used to turn an absolute number into something a person can act on:
    "flatter than 92% of the valley" means more than "2.3 degrees".
    """
    if sorted_sample.size == 0 or not np.isfinite(value):
        return -1
    idx = int(np.searchsorted(sorted_sample, value, side="right"))
    return int(round(100.0 * idx / sorted_sample.size))
