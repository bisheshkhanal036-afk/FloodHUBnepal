"""Benchmark this project's AHP risk surface against METEOR/Fathom's
independent modelled flood depth.

WHAT THIS IS, PRECISELY
=======================
This is **model-to-model benchmarking**, not ground-truth validation.

METEOR (produced with the Fathom global flood hazard framework) is an
independent, physics-based hydraulic flood model: it shares no code, no
input pipeline and no methodology with this project's empirical
multi-criteria weighted overlay. Spatial agreement between the two is
therefore real evidence that the AHP surface behaves like an expert
flood model -- and disagreement is real evidence of a problem.

It is NOT proof that either model is correct. Both are models, and both
lean on digital elevation data, so they can share blind spots. METEOR's
own metadata.txt states it is "not recommended to use the data for
detailed local scale assessments or engineering purposes".

The honest claim this script supports is:

    "benchmarked against an independent expert flood model"

and specifically NOT:

    "validated against observed floods"

Validation against a real flood inventory (Sentinel-1 SAR derived, or
Copernicus EMS / UNOSAT rapid-mapping polygons) remains necessary and is
not replaced by this. This script exists because it is available today,
covers the whole country wall-to-wall, needs no sampling design, and
answers questions the project currently has no answer to at all.

WHAT IT MEASURES
================
1. Rank correlation (Spearman) between the AHP risk surface and METEOR
   modelled depth, over every valid pixel.
2. Class concordance: AHP hazard class (1-5) cross-tabulated against
   METEOR depth bands.
3. AUC of the AHP surface as a predictor of "METEOR models flooding
   here" (depth > FLOOD_DEPTH_THRESHOLD_M). The headline number, and the
   one directly comparable to the AUC figures reported throughout the
   flood-susceptibility literature.
4. Per-criterion AUC: how well does each single criterion predict METEOR
   on its own, before any weighting?
5. Ablation: drop each criterion in turn, recompute, report the change in
   AUC.

(4) and (5) are the point of this script as much as (3) is. This project
has grown to 15 criteria with no evidence about which of them carry
signal, and several are strongly collinear (six derive from the same
DEM). A criterion whose solo AUC is near 0.5, or whose removal does not
move the ensemble AUC, is not earning its weight.

AUC is computed directly from the Mann-Whitney U relationship
(AUC = (U / (n_pos * n_neg))) rather than via sklearn, which is not a
dependency of this project -- scipy already is.

USAGE
=====
    docker compose exec backend python scripts/validate_against_meteor.py

Runs in-process against compute_overlay(), never over HTTP: this needs
hundreds of pixel-level comparisons and several full recomputes, and the
API path would add serialisation and (for the ablation runs) repeated
GeoTIFF writes for no benefit.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from scipy.stats import mannwhitneyu, spearmanr

from app.data import config
from app.data.aoi import AOI
from app.data.reclassify import RECLASSIFIED_NODATA
from app.overlay.compute import RISK_SURFACE_NODATA
from app.overlay.service import OverlayCriterionRequest, compute_overlay

# A pixel is treated as "METEOR models flooding here" above this depth.
# 0.0 would make every pixel inside the modelled floodplain positive
# including ones the model resolved to a true zero depth; a small
# positive threshold asks the sharper question "is there meaningful
# modelled water here". 0.15m matches the lowest band of the standard
# flood-depth-damage convention criteria.js already cites (nuisance
# flooding below ~0.15m).
FLOOD_DEPTH_THRESHOLD_M = 0.15

# Depth bands for the class-concordance cross-tab. Same convention.
DEPTH_BANDS = [
    (0.0, 0.15, "none/nuisance"),
    (0.15, 0.5, "moderate"),
    (0.5, 1.0, "serious"),
    (1.0, 2.0, "severe"),
    (2.0, np.inf, "extreme"),
]

# Kathmandu Valley pilot AOI -- the same box used for the citizen-mode
# performance work, comfortably inside the 1000 km^2 cap and covering the
# populated core of the valley.
DEFAULT_BBOX = (85.22, 27.60, 85.52, 27.82)


# --- the criteria under test -------------------------------------------
# Deliberately EXCLUDES flood_hazard_meteor: benchmarking the AHP surface
# against METEOR while METEOR is itself one of the AHP inputs would be
# circular. This is also the argument for promoting METEOR out of the
# criteria list and into the reference standard permanently.
#
# Rules mirror frontend/src/config/criteria.js's own defaults, so this
# measures the model as the UI actually ships it -- not a hand-tuned
# variant that would flatter the result.

CRITERIA_UNDER_TEST: list[OverlayCriterionRequest] = [
    OverlayCriterionRequest(
        id="dem_elevation",
        source="dem_elevation",
        reclassification_rules=[
            {"min": None, "max": 1300, "risk_class": 5},
            {"min": 1300, "max": 1350, "risk_class": 4},
            {"min": 1350, "max": 1400, "risk_class": 3},
            {"min": 1400, "max": 1500, "risk_class": 2},
            {"min": 1500, "max": None, "risk_class": 1},
        ],
    ),
    OverlayCriterionRequest(
        id="dem_slope",
        source="dem_slope",
        reclassification_rules=[
            {"min": None, "max": 2, "risk_class": 5},
            {"min": 2, "max": 5, "risk_class": 4},
            {"min": 5, "max": 10, "risk_class": 3},
            {"min": 10, "max": 20, "risk_class": 2},
            {"min": 20, "max": None, "risk_class": 1},
        ],
    ),
    OverlayCriterionRequest(
        id="twi",
        source="twi",
        reclassification_rules=[
            {"min": None, "max": 5, "risk_class": 1},
            {"min": 5, "max": 8, "risk_class": 2},
            {"min": 8, "max": 11, "risk_class": 3},
            {"min": 11, "max": 15, "risk_class": 4},
            {"min": 15, "max": None, "risk_class": 5},
        ],
    ),
    OverlayCriterionRequest(
        id="hand",
        source="hand",
        reclassification_rules=[
            {"min": None, "max": 2, "risk_class": 5},
            {"min": 2, "max": 5, "risk_class": 4},
            {"min": 5, "max": 10, "risk_class": 3},
            {"min": 10, "max": 20, "risk_class": 2},
            {"min": 20, "max": None, "risk_class": 1},
        ],
    ),
    OverlayCriterionRequest(
        id="dist_to_river",
        source="dist_to_river",
        reclassification_rules=[
            {"min": None, "max": 100, "risk_class": 5},
            {"min": 100, "max": 200, "risk_class": 4},
            {"min": 200, "max": 300, "risk_class": 3},
            {"min": 300, "max": 400, "risk_class": 2},
            {"min": 400, "max": None, "risk_class": 1},
        ],
    ),
    OverlayCriterionRequest(
        id="drainage_density",
        source="drainage_density",
        reclassification_rules=[
            {"min": None, "max": 1, "risk_class": 1},
            {"min": 1, "max": 2, "risk_class": 2},
            {"min": 2, "max": 3, "risk_class": 3},
            {"min": 3, "max": 4, "risk_class": 4},
            {"min": 4, "max": None, "risk_class": 5},
        ],
    ),
]


@dataclass
class MeteorReference:
    depth_m: np.ndarray
    flooded: np.ndarray  # bool, depth > FLOOD_DEPTH_THRESHOLD_M
    valid: np.ndarray  # bool


def load_meteor_on_grid(grid, flood_type: str, return_period: str) -> MeteorReference:
    """METEOR modelled depth resampled onto `grid`.

    Reads the raw file directly rather than going through
    app/data/meteor_flood.py, deliberately: that module resolves METEOR's
    -9999 sentinel to a real 0.0 m depth so every AOI pixel gets an AHP
    classification (see its docstring). That is right for a criterion,
    but for a *reference standard* the distinction matters -- we want to
    know which pixels the model actually simulated versus never attempted,
    so both are kept explicitly here.
    """
    filename = f"{flood_type}_{return_period}.tif"
    path = config.LOCAL_METEOR_FLOOD_DIR / filename
    if not path.exists():
        raise SystemExit(
            f"METEOR reference not found at {path}.\n"
            "Download https://maps.meteor-project.org/map/flood-npl/download "
            "and place the layer there."
        )

    destination = np.full((grid.height, grid.width), np.nan, dtype=np.float32)
    with rasterio.open(path) as ds:
        reproject(
            source=rasterio.band(ds, 1),
            destination=destination,
            src_transform=ds.transform,
            src_crs=ds.crs,
            dst_transform=grid.transform,
            dst_crs=grid.crs,
            # Nearest, not bilinear: METEOR's raw grid carries sentinel
            # values (-9999 outside the simulated domain, 999 permanent
            # water) that must never be averaged with real depths.
            resampling=Resampling.nearest,
            src_nodata=None,
            dst_nodata=np.nan,
        )

    outside_domain = destination <= -9998.0
    permanent_water = np.isclose(destination, 999.0)
    real_depth = ~(outside_domain | permanent_water) & np.isfinite(destination)

    depth = np.where(real_depth, destination, 0.0).astype(np.float32)
    # Permanent water counts as flooded at the top of the depth range.
    depth = np.where(permanent_water, 5.0, depth)

    valid = real_depth | outside_domain | permanent_water
    flooded = (depth > FLOOD_DEPTH_THRESHOLD_M) & valid

    return MeteorReference(depth_m=depth, flooded=flooded, valid=valid)


def auc_mann_whitney(scores: np.ndarray, positive: np.ndarray) -> float | None:
    """AUC via the Mann-Whitney U statistic.

    AUC is exactly U / (n_pos * n_neg) -- the probability that a randomly
    chosen positive pixel scores above a randomly chosen negative one.
    Used instead of sklearn.metrics.roc_auc_score because scipy is
    already a dependency of this project and sklearn is not.

    Returns None where AUC is undefined (one class absent).
    """
    pos = scores[positive]
    neg = scores[~positive]
    if pos.size == 0 or neg.size == 0:
        return None
    u_statistic, _ = mannwhitneyu(pos, neg, alternative="greater")
    return float(u_statistic / (pos.size * neg.size))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flood-type", default="FD", choices=("FD", "FU", "P"))
    parser.add_argument("--return-period", default="1in100")
    parser.add_argument("--bbox", nargs=4, type=float, default=list(DEFAULT_BBOX))
    parser.add_argument("--out", default="validation_meteor.json")
    parser.add_argument("--skip-ablation", action="store_true")
    parser.add_argument(
        "--only",
        default=None,
        help="Comma-separated criterion ids to restrict the run to, e.g. 'dist_to_river,hand,dem_elevation'. Used to test whether a pruned "
             "model matches or beats the full one.",
    )
    args = parser.parse_args()

    aoi = AOI(bbox_4326=tuple(args.bbox))

    criteria = CRITERIA_UNDER_TEST
    if args.only:
        wanted = {x.strip() for x in args.only.split(',') if x.strip()}
        unknown = wanted - {c.id for c in CRITERIA_UNDER_TEST}
        if unknown:
            raise SystemExit(f'unknown criterion id(s): {sorted(unknown)}')
        criteria = [c for c in CRITERIA_UNDER_TEST if c.id in wanted]

    ids = [c.id for c in criteria]
    equal = {cid: 1.0 / len(ids) for cid in ids}

    print(f"AOI: {args.bbox}")
    print(f"Reference: METEOR {args.flood_type}_{args.return_period}")
    print(f"Criteria under test ({len(ids)}): {', '.join(ids)}\n")

    print("Computing full AHP surface (equal weights)...")
    full = compute_overlay(aoi, criteria, equal, complete=True)
    grid = full.risk_surface.grid
    risk = full.risk_surface.risk_surface

    meteor = load_meteor_on_grid(grid, args.flood_type, args.return_period)

    usable = (risk != RISK_SURFACE_NODATA) & np.isfinite(risk) & meteor.valid
    n_usable = int(usable.sum())
    if n_usable == 0:
        raise SystemExit("No overlapping valid pixels between the AHP surface and METEOR.")

    risk_v = risk[usable]
    depth_v = meteor.depth_m[usable]
    flooded_v = meteor.flooded[usable]

    print(f"  usable pixels: {n_usable:,}")
    print(f"  METEOR-flooded (>{FLOOD_DEPTH_THRESHOLD_M} m): "
          f"{flooded_v.sum():,} ({100 * flooded_v.mean():.2f}%)\n")

    results: dict = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "reference": f"METEOR {args.flood_type}_{args.return_period}",
        "caveat": (
            "Model-to-model benchmarking against an independent expert flood model, "
            "NOT validation against observed floods."
        ),
        "bbox_4326": list(args.bbox),
        "flood_depth_threshold_m": FLOOD_DEPTH_THRESHOLD_M,
        "usable_pixels": n_usable,
        "meteor_flooded_fraction": float(flooded_v.mean()),
        "criteria": ids,
    }

    # --- 1. rank correlation -------------------------------------------
    rho, pval = spearmanr(risk_v, depth_v)
    results["spearman_rho_vs_depth"] = float(rho)
    results["spearman_p"] = float(pval)
    print(f"Spearman rho (risk vs modelled depth): {rho:+.4f}")

    # --- 2. ensemble AUC ------------------------------------------------
    ensemble_auc = auc_mann_whitney(risk_v, flooded_v)
    results["ensemble_auc"] = ensemble_auc
    print(f"Ensemble AUC (15-criterion AHP vs METEOR floodplain): {ensemble_auc:.4f}\n")

    # --- 3. per-criterion solo AUC --------------------------------------
    print("Per-criterion solo AUC (reclassified 1-5, unweighted):")
    solo: dict[str, float | None] = {}
    for cr in full.criterion_rasters:
        arr = cr.reclassified
        ok = usable & (arr != RECLASSIFIED_NODATA)
        if ok.sum() == 0:
            solo[cr.criterion_id] = None
            continue
        solo[cr.criterion_id] = auc_mann_whitney(
            arr[ok].astype(np.float64), meteor.flooded[ok]
        )
    for cid, val in sorted(solo.items(), key=lambda kv: (kv[1] is None, -(kv[1] or 0))):
        print(f"  {cid:22s} {'n/a' if val is None else f'{val:.4f}'}")
    results["solo_auc"] = solo

    # --- 4. class concordance -------------------------------------------
    hazard_class = np.clip(np.ceil(risk_v * 5), 1, 5).astype(int)
    concordance = {}
    for lo, hi, name in DEPTH_BANDS:
        band = (depth_v >= lo) & (depth_v < hi)
        if band.sum() == 0:
            continue
        counts = np.bincount(hazard_class[band], minlength=6)[1:6]
        concordance[name] = {
            "pixels": int(band.sum()),
            "mean_hazard_class": float(hazard_class[band].mean()),
            "class_counts_1_to_5": counts.tolist(),
        }
    results["class_concordance"] = concordance
    print("\nMean AHP hazard class by METEOR depth band:")
    for name, d in concordance.items():
        print(f"  {name:16s} n={d['pixels']:>9,}  mean class {d['mean_hazard_class']:.2f}")

    # --- 5. ablation ----------------------------------------------------
    if not args.skip_ablation and ensemble_auc is not None:
        print("\nAblation (drop one criterion, recompute):")
        ablation = {}
        for drop in ids:
            kept = [c for c in criteria if c.id != drop]
            w = {c.id: 1.0 / len(kept) for c in kept}
            res = compute_overlay(aoi, kept, w, complete=True)
            r = res.risk_surface.risk_surface
            ok = (r != RISK_SURFACE_NODATA) & np.isfinite(r) & meteor.valid
            a = auc_mann_whitney(r[ok], meteor.flooded[ok])
            delta = None if a is None else a - ensemble_auc
            ablation[drop] = {"auc_without": a, "delta": delta}
            print(f"  without {drop:22s} AUC {a:.4f}  ({delta:+.4f})")
        results["ablation"] = ablation

    out = Path(args.out)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
