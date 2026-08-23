"""Discrete 1-5 hazard-class derivation from the continuous risk_surface —
the "vulnerability classification" feature's Part 1, per SPEC.md §3.4's
already-documented R_norm formula. Kept as its own small module (not
folded into compute.py) since compute.py's own docstring frames itself
as producing ONLY the continuous [0,1] surface deliberately ("discrete
classes are derived from this value separately, at display/legend time"
— schemas/risk_surface.schema.json's own description) — this module IS
that separate derivation step, not a change to compute.py's own contract.

R_norm = (R - 1) / (5 - 1), where R = sum(weight_i * class_i) is a
convex combination (weights sum to 1) of each contributing criterion's
own discrete class (1-5) AT THAT PIXEL. Recovering "the" class from
R_norm is necessarily a re-discretization of a continuous composite
score, not literally undoing a lost single value — at any pixel where
two criteria disagree (e.g. elevation says class 3, dist_to_river says
class 5), R_norm reflects their weighted blend, not either one alone.
This is standard practice for AHP-overlay flood susceptibility mapping
(the Siraha/Lee et al. approach this feature matches discretizes the
same kind of continuous composite index into 5 classes for reporting/
mapping), not a shortcut unique to this implementation — flagged here
so it's never mistaken for "recovering a true underlying per-pixel
class" that was somehow lost.

Bucketing rule: ROUND-NEAREST, not floor. Inverting the formula gives
R = R_norm * 4 + 1, a continuous value in [1, 5]; round-nearest maps
each class k to R in [k-0.5, k+0.5) (clamped to [1, 5]), the standard
way to discretize a continuous score into equal-width bins centered on
each integer label. Floor was considered and rejected: it would
systematically bias every pixel down by up to just-under-1 whole class
(e.g. R=4.99 -- essentially unambiguously class 5 territory -- would
floor to class 4), which floor's own asymmetry makes a strictly worse
approximation than round-nearest's evenly-distributed error on either
side of each integer.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio

from app.data.grid import AOIGrid

from .compute import RISK_CLASS_MAX, RISK_CLASS_MIN, RISK_SURFACE_NODATA
from .geotiff import write_hazard_class_geotiff

# 0, not a value in 1-5, for the same reason reclassify.RECLASSIFIED_NODATA
# is 0 -- unambiguous as "no class assigned" against the real 1-5 range.
HAZARD_CLASS_NODATA = 0

HAZARD_CLASS_LABELS: dict[int, str] = {
    1: "Very Low",
    2: "Low",
    3: "Moderate",
    4: "High",
    5: "Very High",
}


def risk_surface_to_hazard_classes(risk_surface: np.ndarray, nodata: float) -> np.ndarray:
    """Bucket a continuous risk_surface (values in [0, 1], or `nodata`)
    into discrete integer hazard classes 1-5 (uint8), `HAZARD_CLASS_NODATA`
    (0) at nodata pixels. See this module's own docstring for the formula
    and the round-vs-floor reasoning.
    """
    nodata_mask = risk_surface == nodata
    r = risk_surface.astype(np.float64) * (RISK_CLASS_MAX - RISK_CLASS_MIN) + RISK_CLASS_MIN
    hazard_class = np.clip(np.round(r), RISK_CLASS_MIN, RISK_CLASS_MAX)
    return np.where(nodata_mask, HAZARD_CLASS_NODATA, hazard_class).astype(np.uint8)


def materialize_hazard_classes_from_risk_surface_tif(risk_surface_tif_path: Path, hazard_classes_tif_path: Path) -> None:
    """Derives + writes the discrete hazard-class GeoTIFF straight from an
    already-materialized risk_surface GeoTIFF on disk -- no AOI, no
    recompute of the risk surface itself, no dependency on
    overlay/report.py's heavier pipeline. Everything needed (the array,
    its nodata, its grid) is already embedded in the risk_surface .tif's
    own metadata, which is exactly why GET /hazard_classes/{cache_key}.tif
    (router.py) can serve this as a lightweight, standalone download for
    anyone who already has a cache_key from POST /compute, without ever
    calling POST /overlay/report at all.
    """
    with rasterio.open(risk_surface_tif_path) as src:
        risk_surface = src.read(1)
        nodata = src.nodata
        grid = AOIGrid(
            crs=str(src.crs),
            resolution_m=src.transform.a,
            origin_x=src.transform.c,
            origin_y=src.transform.f,
            width=src.width,
            height=src.height,
        )

    hazard_class_raster = risk_surface_to_hazard_classes(risk_surface, nodata)
    write_hazard_class_geotiff(hazard_classes_tif_path, hazard_class_raster, grid, HAZARD_CLASS_NODATA)


# Sanity self-check, not a runtime guard: RISK_SURFACE_NODATA (-9999.0) must
# never itself land inside [0, 1] after the linear transform above, or a
# real nodata pixel could accidentally be classified as a real hazard
# class instead of HAZARD_CLASS_NODATA. -9999.0 is nowhere near [0, 1], so
# this holds trivially today, but pinned here as an explicit assertion
# (evaluated at import time) rather than left as an implicit assumption --
# if RISK_SURFACE_NODATA ever changed to something less obviously safe,
# this would fail loudly at import rather than silently misclassifying.
assert not (0.0 <= RISK_SURFACE_NODATA <= 1.0), "RISK_SURFACE_NODATA must never fall inside the valid [0, 1] range"
