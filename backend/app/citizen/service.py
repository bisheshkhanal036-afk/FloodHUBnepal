"""Citizen Mode's assessment pipeline: point in, plain-language answer out.

Deliberately a thin layer over machinery that already exists. It computes
nothing new — it selects the validated profile (profile.py), runs the
existing overlay engine over the pilot area, samples the result at one
point, and turns the per-criterion values there into sentences a person
can act on.

Three things this module is careful about:

1. **Reasons come from the raw values, not the score.** Telling someone
   "HIGH risk" without saying why is not an awareness tool, it is an
   oracle. Every reason below is derived from a criterion's actual value
   at that exact location, with the number included, so the user can
   sanity-check it against what they can see out of a window.

2. **The AOI is fixed, not per-request.** AOI.cache_key() hashes the
   bbox to 8 decimal places, so a per-user bounding box would miss the
   cache on every single request and cost a ~60 s recompute. One shared
   pilot-area surface means every request after the first is a cache hit,
   and HAND/TWI get a proper catchment rather than a box clipped around
   somebody's house (SPEC.md documents flow accumulation being unreliable
   near a bbox edge).

3. **Out-of-area is answered honestly.** A point outside the pilot area
   gets "not covered yet", never a silently-computed answer over a
   different region.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import numpy as np
from pyproj import Transformer

from app.data.aoi import AOI
from app.data.cache import cached_or_compute
from app.overlay.compute import RISK_SURFACE_NODATA, CriterionRaster
from app.overlay.service import OverlayCriterionRequest, compute_overlay

from .profile import (
    CITIZEN_CRITERIA,
    N_CLASSES,
    RISK_DIRECTION,
    RISK_LEVEL_BY_CLASS,
    normalized_weights,
)

logger = logging.getLogger(__name__)

# The pilot area: Kathmandu Valley. Fixed for phase 1 (see this module's
# docstring point 2 for why it is not derived per request).
PILOT_BBOX = (85.22, 27.60, 85.52, 27.82)
PILOT_NAME_EN = "Kathmandu Valley"
PILOT_NAME_NE = "काठमाडौं उपत्यका"

# Quantile breaks are computed from the pilot surface's own data, which is
# what the validation measured (+0.036 AUC over the previously hardcoded
# breaks). Bumped if the break derivation itself changes.
_BREAKS_VERSION = "v1"


@dataclass
class Reason:
    """One plain-language explanation of the score, with the number that
    produced it so the user can check it themselves.
    """

    code: str
    value: float
    unit: str
    severity: str  # "raises" | "lowers"


@dataclass
class Assessment:
    covered: bool
    lon: float
    lat: float
    risk_level: str | None = None
    hazard_class: int | None = None
    risk_score: float | None = None
    reasons: list[Reason] = field(default_factory=list)
    cache_key: str | None = None


def _quantile_rules(values: np.ndarray, criterion_id: str) -> list[dict]:
    """Quintile breaks from the pilot area's own distribution.

    LITERATURE_REVIEW_THRESHOLDS.md documents why borrowed absolute breaks
    are not used: applied to this valley, the published Bagmati-basin
    elevation breaks put 56.9% of the area into a single class and leave
    the top-risk class completely empty. Breaks derived from the data
    actually being classified discriminate; borrowed ones do not.
    """
    q = [float(np.percentile(values, p)) for p in (20, 40, 60, 80)]
    for i in range(1, len(q)):
        if q[i] <= q[i - 1]:
            q[i] = q[i - 1] + 1e-6

    ascending = RISK_DIRECTION[criterion_id] == "ascending"
    classes = [1, 2, 3, 4, 5] if ascending else [5, 4, 3, 2, 1]
    edges = [None] + q + [None]
    return [{"min": edges[i], "max": edges[i + 1], "risk_class": classes[i]} for i in range(N_CLASSES)]


_RAW_SOURCE = {
    "hand": ("app.data.hydrology", "get_hand", "hand", "m"),
    "dem_elevation": ("app.data.dem", "get_dem", "elevation_m", "m"),
    "dem_slope": ("app.data.dem", "get_dem", "slope_degrees", "°"),
    "twi": ("app.data.hydrology", "get_twi", "twi", ""),
    "drainage_density": ("app.data.hydrology", "get_drainage_density", "drainage_density", "km/km²"),
}


def _raw_layer(aoi: AOI, criterion_id: str):
    import importlib

    mod_name, fn_name, attr, unit = _RAW_SOURCE[criterion_id]
    res = getattr(importlib.import_module(mod_name), fn_name)(aoi)
    return getattr(res, attr), res.nodata, unit


@dataclass
class PilotSurface:
    """Everything an assessment needs, computed once for the pilot area."""

    risk: np.ndarray
    grid: object
    cache_key: str
    criterion_rasters: list[CriterionRaster]
    raw: dict[str, tuple[np.ndarray, float, str]]


# The pilot surface, held in memory for the life of the process.
#
# cached_or_compute (app/data/cache.py) is a DISK cache -- it unpickles
# from disk on every call, with no in-memory layer. That is the right
# design there, since it backs many different AOIs across many criterion
# sources and memoising all of them would be unbounded. But Citizen Mode
# has exactly ONE surface, every request needs it, and it is large:
# measured at 215 MB, taking 6.7 s to unpickle cold and ~2.4 s warm.
# Without this memo every single /api/citizen/assess request paid that
# again, which is most of the ~1.8-5 s a request was taking.
#
# Bounded by construction: one entry, replaced only if the AOI or breaks
# version change. The lock makes the first concurrent burst after start
# compute once rather than N times -- FastAPI serves requests from a
# threadpool, so simultaneous cold requests are the normal case, not an
# edge case.
_pilot_surface: "PilotSurface | None" = None
_pilot_key: tuple | None = None
_pilot_lock = threading.Lock()


def get_pilot_surface() -> PilotSurface:
    """The pilot-area risk surface: in memory if already loaded, else
    from the disk cache, else computed (~60 s).

    Call warm_pilot_surface() at startup to keep that cost off the first
    user request.
    """
    global _pilot_surface, _pilot_key

    key = (PILOT_BBOX, _BREAKS_VERSION, CITIZEN_CRITERIA)
    if _pilot_surface is not None and _pilot_key == key:
        return _pilot_surface

    with _pilot_lock:
        # Re-check inside the lock: another thread may have loaded it
        # while this one waited.
        if _pilot_surface is not None and _pilot_key == key:
            return _pilot_surface
        surface = _load_pilot_surface()
        _pilot_surface, _pilot_key = surface, key
        return surface


def warm_pilot_surface() -> None:
    """Load (or compute) the pilot surface ahead of any user request.

    Intended for application startup, off the request path -- see
    app/main.py's lifespan hook. Failures are logged and swallowed on
    purpose: a warm-up that cannot reach its data must not stop the
    service from starting, since every other endpoint is unaffected and
    /api/citizen/assess will simply retry (and surface a real error) on
    first use.
    """
    try:
        t0 = time.monotonic()
        get_pilot_surface()
        logger.info("citizen: pilot surface warm in %.1fs", time.monotonic() - t0)
    except Exception:
        logger.exception("citizen: pilot surface warm-up failed; will retry on first request")


def _load_pilot_surface() -> PilotSurface:
    aoi = AOI(bbox_4326=PILOT_BBOX)

    def _compute() -> PilotSurface:
        logger.info("citizen: computing pilot surface for %s", PILOT_BBOX)
        raw: dict[str, tuple[np.ndarray, float, str]] = {}
        criteria: list[OverlayCriterionRequest] = []

        for cid in CITIZEN_CRITERIA:
            arr, nodata, unit = _raw_layer(aoi, cid)
            raw[cid] = (arr, nodata, unit)
            usable = arr[(arr != nodata) & np.isfinite(arr)]
            criteria.append(
                OverlayCriterionRequest(
                    id=cid, source=cid, reclassification_rules=_quantile_rules(usable, cid)
                )
            )

        result = compute_overlay(aoi, criteria, normalized_weights(), complete=True)
        return PilotSurface(
            risk=result.risk_surface.risk_surface,
            grid=result.risk_surface.grid,
            cache_key=result.cache_key,
            criterion_rasters=result.criterion_rasters,
            raw=raw,
        )

    return cached_or_compute("citizen_pilot", aoi, _compute, version=_BREAKS_VERSION)


def _pixel_for(grid, lon: float, lat: float) -> tuple[int, int] | None:
    to_grid = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    x, y = to_grid.transform(lon, lat)
    col, row = ~grid.transform * (x, y)
    r, c = int(row), int(col)
    if 0 <= r < grid.height and 0 <= c < grid.width:
        return r, c
    return None


# A criterion earns a reason when its OWN reclassified risk class at this
# point is extreme — >= RAISES_AT means it pushed the score up, <=
# LOWERS_AT means it pulled it down.
#
# Deliberately derived from the same reclassification that produced the
# score, not from absolute thresholds. An earlier version used
# hand-picked cutoffs (e.g. "HAND < 5 m") and produced a real bug: a
# point in Sinamangal scored HIGH with zero reasons attached, because the
# model classifies against this valley's own quintiles while the reason
# rules were testing arbitrary absolute values. Reasons that can disagree
# with the number they explain are worse than no reasons at all.
RAISES_AT = 4
LOWERS_AT = 2

# Which reason code to use for each criterion in each direction.
_REASON_CODE = {
    "hand": ("hand_low", "hand_high"),
    "dem_elevation": ("elevation_low", "elevation_high"),
    "dem_slope": ("slope_flat", "slope_steep"),
    "twi": ("twi_high", "twi_low"),
    "drainage_density": ("drainage_high", "drainage_low"),
}


def _build_reasons(surface: PilotSurface, r: int, c: int) -> list[Reason]:
    """The criteria that most moved this point's score, in plain terms.

    Ranked by each criterion's actual contribution to the weighted sum
    (its published weight x how extreme its class is), so the reasons
    shown are the ones that genuinely drove the answer rather than the
    first ones in the list.
    """
    weights = normalized_weights()
    by_id = {cr.criterion_id: cr for cr in surface.criterion_rasters}

    scored: list[tuple[float, Reason]] = []
    for cid in CITIZEN_CRITERIA:
        raster = by_id.get(cid)
        if raster is None:
            continue
        cls = int(raster.reclassified[r, c])
        if cls < 1 or cls > N_CLASSES:  # RECLASSIFIED_NODATA is 0
            continue

        arr, nodata, unit = surface.raw[cid]
        value = float(arr[r, c])
        if value == nodata or not np.isfinite(value):
            continue

        raises_code, lowers_code = _REASON_CODE[cid]
        if cls >= RAISES_AT:
            severity, code = "raises", raises_code
        elif cls <= LOWERS_AT:
            severity, code = "lowers", lowers_code
        else:
            continue

        # Distance from the neutral middle class, weighted by how much
        # this criterion counts at all.
        influence = weights.get(cid, 0.0) * abs(cls - 3)
        scored.append((influence, Reason(code=code, value=round(value, 1), unit=unit, severity=severity)))

    scored.sort(key=lambda t: (-t[0], 0 if t[1].severity == "raises" else 1))
    return [reason for _, reason in scored[:3]]


def assess(lon: float, lat: float) -> Assessment:
    """Flood susceptibility at one point, with reasons."""
    if not (PILOT_BBOX[0] <= lon <= PILOT_BBOX[2] and PILOT_BBOX[1] <= lat <= PILOT_BBOX[3]):
        return Assessment(covered=False, lon=lon, lat=lat)

    surface = get_pilot_surface()
    px = _pixel_for(surface.grid, lon, lat)
    if px is None:
        return Assessment(covered=False, lon=lon, lat=lat)

    r, c = px
    score = float(surface.risk[r, c])
    if score == RISK_SURFACE_NODATA or not np.isfinite(score):
        return Assessment(covered=False, lon=lon, lat=lat)

    hazard_class = int(np.clip(np.ceil(score * N_CLASSES), 1, N_CLASSES))

    return Assessment(
        covered=True,
        lon=lon,
        lat=lat,
        risk_level=RISK_LEVEL_BY_CLASS[hazard_class],
        hazard_class=hazard_class,
        risk_score=round(score, 4),
        reasons=_build_reasons(surface, r, c),
        cache_key=surface.cache_key,
    )
