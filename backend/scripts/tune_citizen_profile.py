"""Choose the citizen-mode criteria profile by measuring it, not by
picking it.

Citizen mode fixes the criteria, the weights and the class breaks on the
user's behalf — they get one tap and one answer, with no AHP matrix and
no break editor. That convenience is only defensible if the fixed
configuration is the best one we can evidence. This script tests the
candidate configurations against the observed BIPAD flood inventory
(success-rate curve, same method as validate_against_inventory.py) and
reports AUC for each.

Configurations tested
=====================
Weighting schemes:
  equal      - 1/n each, the current default
  published  - Chaudhary et al. (2024) Sustainability 16(16), 7101, Table 4,
               AHP eigenvector weights for THIS study area (CR = 0.052),
               renormalised over whichever criteria are present:
                 rainfall 23, elevation 22, slope 16, TWI 10,
                 distance-from-river 8, curvature 8, LULC 5,
                 drainage density 4, geology 2, soil 2

Break schemes:
  hardcoded  - the values currently shipped in frontend/src/config/criteria.js
  quantile   - per-criterion quintiles computed from THIS AOI's own data

The quantile scheme tests the central recommendation of
LITERATURE_REVIEW_THRESHOLDS.md: absolute breaks borrowed from a
differently-scaled study area destroy discrimination inside this valley
(elevation 966-1491 m puts 56.9% of the valley in one class), so breaks
should be derived from the AOI's own distribution. Quintiles are used
rather than Jenks purely so this script has no extra dependency; the
backend already exposes Jenks via POST /api/overlay/criteria/breaks and
the production profile should use it.

Risk direction per criterion is taken from criteria.js and is NOT tuned
here — direction is physics, not a free parameter.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from app.data.aoi import AOI
from app.overlay.compute import RISK_SURFACE_NODATA
from app.overlay.service import OverlayCriterionRequest, compute_overlay

sys.path.insert(0, "/app")
from validate_against_inventory import (  # noqa: E402
    INVENTORY_PATH,
    load_inventory,
    sample_points,
    success_rate_curve,
)

DEFAULT_BBOX = (85.22, 27.60, 85.52, 27.82)

# Chaudhary et al. 2024, Table 4 — criteria weights (%) for Kathmandu
# Valley, CR = 0.052.
PUBLISHED_WEIGHTS = {
    "rainfall": 23,
    "dem_elevation": 22,
    "dem_slope": 16,
    "twi": 10,
    "dist_to_river": 8,
    "curvature": 8,
    "worldcover_land_cover": 5,
    "drainage_density": 4,
    "geology": 2,
    "soil_infiltration": 2,
}

# ascending  = high raw value -> high flood risk
# descending = low raw value  -> high flood risk
RISK_DIRECTION = {
    "dem_elevation": "descending",
    "dem_slope": "descending",
    "twi": "ascending",
    "hand": "descending",
    "dist_to_river": "descending",
    "drainage_density": "ascending",
}

SOURCE_FN = {
    "dem_elevation": ("app.data.dem", "get_dem", "elevation_m"),
    "dem_slope": ("app.data.dem", "get_dem", "slope_degrees"),
    "twi": ("app.data.hydrology", "get_twi", "twi"),
    "hand": ("app.data.hydrology", "get_hand", "hand"),
    "dist_to_river": ("app.data.distance_raster", "get_distance_to_river", "distance_m"),
    "drainage_density": ("app.data.hydrology", "get_drainage_density", "drainage_density"),
}


def quantile_rules(aoi: AOI, criterion_id: str) -> list[dict]:
    """Quintile breaks from this AOI's own distribution, with risk classes
    assigned according to the criterion's physical risk direction.
    """
    import importlib

    mod_name, fn_name, attr = SOURCE_FN[criterion_id]
    mod = importlib.import_module(mod_name)
    res = getattr(mod, fn_name)(aoi)
    arr = getattr(res, attr)
    nodata = res.nodata
    vals = arr[arr != nodata]
    vals = vals[np.isfinite(vals)]

    q = [float(np.percentile(vals, p)) for p in (20, 40, 60, 80)]
    # Guard against degenerate/duplicate breaks.
    for i in range(1, len(q)):
        if q[i] <= q[i - 1]:
            q[i] = q[i - 1] + 1e-6

    ascending = RISK_DIRECTION[criterion_id] == "ascending"
    classes = [1, 2, 3, 4, 5] if ascending else [5, 4, 3, 2, 1]
    edges = [None] + q + [None]
    return [
        {"min": edges[i], "max": edges[i + 1], "risk_class": classes[i]}
        for i in range(5)
    ]


def build_criteria(aoi: AOI, ids: list[str], breaks: str) -> list[OverlayCriterionRequest]:
    from validate_against_meteor import CRITERIA_UNDER_TEST

    by_id = {c.id: c for c in CRITERIA_UNDER_TEST}
    out = []
    for cid in ids:
        rules = by_id[cid].reclassification_rules if breaks == "hardcoded" else quantile_rules(aoi, cid)
        out.append(OverlayCriterionRequest(id=cid, source=cid, reclassification_rules=rules))
    return out


def weights_for(ids: list[str], scheme: str) -> dict[str, float]:
    if scheme == "equal":
        return {i: 1.0 / len(ids) for i in ids}
    raw = {i: PUBLISHED_WEIGHTS.get(i, 1) for i in ids}
    total = sum(raw.values())
    return {i: v / total for i, v in raw.items()}


def evaluate(aoi, ids, weight_scheme, break_scheme, split_year=None) -> tuple[float, int]:
    criteria = build_criteria(aoi, ids, break_scheme)
    weights = weights_for(ids, weight_scheme)
    res = compute_overlay(aoi, criteria, weights, complete=True)
    grid = res.risk_surface.grid
    risk = res.risk_surface.risk_surface
    valid = (risk != RISK_SURFACE_NODATA) & np.isfinite(risk)

    half = "test" if split_year else "all"
    pts = load_inventory(INVENTORY_PATH, aoi.bbox_4326, split_year, half)
    values, _ = sample_points(risk, grid, valid, pts)
    if values.size < 10:
        return float("nan"), int(values.size)
    _, _, auc = success_rate_curve(risk, valid, values)
    return auc, int(values.size)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bbox", nargs=4, type=float, default=list(DEFAULT_BBOX))
    ap.add_argument("--out", default="/app/data/cache/citizen_profile_tuning.json")
    args = ap.parse_args()

    aoi = AOI(bbox_4326=tuple(args.bbox))

    SIX = ["dem_elevation", "dem_slope", "twi", "hand", "dist_to_river", "drainage_density"]
    NO_DR = [c for c in SIX if c != "dist_to_river"]
    HAND_LED = ["hand", "dem_elevation", "twi", "dem_slope"]

    candidates = [
        ("6-criterion", SIX, "equal", "hardcoded"),
        ("6-criterion", SIX, "published", "hardcoded"),
        ("6-criterion", SIX, "equal", "quantile"),
        ("6-criterion", SIX, "published", "quantile"),
        ("5-crit (no dist_to_river)", NO_DR, "equal", "quantile"),
        ("5-crit (no dist_to_river)", NO_DR, "published", "quantile"),
        ("4-crit HAND-led", HAND_LED, "equal", "quantile"),
        ("4-crit HAND-led", HAND_LED, "published", "quantile"),
    ]

    print(f"AOI: {args.bbox}\nValidating against observed BIPAD flood inventory\n")
    print(f"{'profile':28s} {'weights':10s} {'breaks':10s} {'AUC':>8s}")
    print("-" * 60)

    results = []
    best = None
    for name, ids, wscheme, bscheme in candidates:
        auc, n = evaluate(aoi, ids, wscheme, bscheme)
        results.append({"profile": name, "criteria": ids, "weights": wscheme,
                        "breaks": bscheme, "auc": auc, "n_points": n})
        print(f"{name:28s} {wscheme:10s} {bscheme:10s} {auc:8.4f}")
        if best is None or auc > best["auc"]:
            best = results[-1]

    print("\nBEST:", best["profile"], "|", best["weights"], "weights |", best["breaks"],
          "breaks | AUC %.4f" % best["auc"])

    # Temporal holdout on the winner — the stronger test.
    auc_pred, n_pred = evaluate(aoi, best["criteria"], best["weights"], best["breaks"], split_year=2020)
    print(f"\nPrediction-rate (events 2020+ only, n={n_pred}): AUC {auc_pred:.4f}")

    payload = {"candidates": results, "best": best,
               "prediction_rate_2020plus": {"auc": auc_pred, "n_points": n_pred}}
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
