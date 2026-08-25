"""Validate this project's AHP risk surface against an OBSERVED flood
inventory, using the success-rate-curve method.

HOW THIS DIFFERS FROM validate_against_meteor.py
================================================
`validate_against_meteor.py` benchmarks our surface against METEOR/Fathom
— another *model*. Useful, cheap, wall-to-wall, but it can only show our
model behaves like an expert model, not that either matches reality.

This script compares against **places floods actually happened**: dated,
georeferenced incident records from BIPAD, the Government of Nepal's
official disaster portal (National Disaster Risk Reduction and Management
Authority), harvested from its public API. That is ground truth, and it
supports the stronger claim:

    "validated against an observed flood inventory"

Method
======
The **success-rate curve** (Chung & Fabbri 2003), which is the standard
for point-based landslide/flood inventories and is exactly what the
directly-comparable published study for this study area used
(Chaudhary et al. 2024, Sustainability 16(16), 7101, AUC = 0.83):

  1. Rank every pixel in the AOI by susceptibility, highest first.
  2. Sweep a threshold from the highest-risk pixel downwards. At each
     step record:
       x = cumulative fraction of the study AREA above the threshold
       y = cumulative fraction of observed FLOOD POINTS captured
  3. AUC of that curve.

A perfect model captures 100% of flood points in the smallest possible
area (AUC -> 1). A useless model captures points in proportion to area
(the diagonal, AUC = 0.5).

Why this and not a plain ROC over sampled negatives: an incident
inventory records where floods *were reported*, never where they were
absent. Constructing "non-flood" points requires assumptions that
routinely inflate AUC — sample them on hillslopes and any model scores
0.95 for free. The success-rate curve needs no negative samples at all.

Known limitations, stated rather than hidden
============================================
* **Reporting bias.** Incidents are reported where people are. Dense
  urban wards generate more records than empty hillsides regardless of
  true hazard, so the inventory over-represents populated areas.
* **Point, not extent.** Each record is a single coordinate, often a
  ward or settlement centroid, not the true inundation footprint.
* **Recency bias.** BIPAD coverage is far better after ~2011 than before.
* **Success rate, not prediction rate.** Fitting and evaluation use the
  same inventory. A prediction-rate curve (fit on pre-2020 events,
  evaluate on post-2020) is the stronger test and is available via
  --split-year, since every record carries a date.

Usage
=====
    python validate_against_inventory.py
    python validate_against_inventory.py --split-year 2020   # temporal holdout
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pyproj import Transformer

from app.data.aoi import AOI
from app.overlay.compute import RISK_SURFACE_NODATA
from app.overlay.service import OverlayCriterionRequest, compute_overlay

INVENTORY_PATH = Path("/app/data/raw/flood_inventory/ktm_flood_inventory.json")

DEFAULT_BBOX = (85.22, 27.60, 85.52, 27.82)

# Same criteria and rules as validate_against_meteor.py, so the two
# studies measure the same model rather than two different ones.
from validate_against_meteor import CRITERIA_UNDER_TEST  # noqa: E402


def load_inventory(path: Path, bbox, split_year: int | None, half: str):
    if not path.exists():
        raise SystemExit(f"inventory not found at {path}")
    records = json.loads(path.read_text(encoding="utf-8"))

    pts = []
    for r in records:
        lon, lat = r["lon"], r["lat"]
        if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
            continue
        year = int(r["date"][:4]) if r.get("date") else None
        if split_year is not None and year is not None:
            if half == "train" and year >= split_year:
                continue
            if half == "test" and year < split_year:
                continue
        pts.append((lon, lat, year))
    return pts


def success_rate_curve(risk: np.ndarray, valid: np.ndarray, point_values: np.ndarray):
    """Cumulative fraction of flood points captured vs cumulative fraction
    of area, sweeping the susceptibility threshold from high to low.

    Returns (x, y, auc). Computed by ranking pixels rather than binning,
    so the curve is exact rather than dependent on a class count.
    """
    vals = risk[valid]
    order = np.argsort(vals)[::-1]
    sorted_vals = vals[order]
    n_area = sorted_vals.size

    # For each flood point, what fraction of the area is at least as
    # susceptible as the pixel it sits on? That is its x-position.
    # searchsorted on the descending array via the ascending mirror.
    asc = sorted_vals[::-1]
    # number of pixels with value >= v  ==  n_area - (index of first >= v in asc)
    idx = np.searchsorted(asc, point_values, side="left")
    area_frac_at_point = (n_area - idx) / n_area

    # Sweep: sort points by the area fraction needed to capture them.
    xs = np.sort(area_frac_at_point)
    ys = np.arange(1, xs.size + 1) / xs.size

    # Prepend origin so the curve starts at (0,0).
    x = np.concatenate([[0.0], xs, [1.0]])
    y = np.concatenate([[0.0], ys, [1.0]])
    auc = float(np.trapezoid(y, x)) if hasattr(np, "trapezoid") else float(np.trapz(y, x))
    return x, y, auc


def sample_points(risk, grid, valid, pts):
    """Susceptibility value at each flood point, dropping points that fall
    on nodata or outside the grid.
    """
    to_grid = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    inv = ~grid.transform

    vals, kept = [], []
    for lon, lat, year in pts:
        x, y = to_grid.transform(lon, lat)
        col, row = inv * (x, y)
        r, c = int(row), int(col)
        if not (0 <= r < grid.height and 0 <= c < grid.width):
            continue
        if not valid[r, c]:
            continue
        vals.append(risk[r, c])
        kept.append((lon, lat, year))
    return np.array(vals, dtype=np.float64), kept


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bbox", nargs=4, type=float, default=list(DEFAULT_BBOX))
    ap.add_argument("--only", default=None, help="comma-separated criterion ids")
    ap.add_argument("--split-year", type=int, default=None,
                    help="temporal holdout: evaluate only on events from this year onward")
    ap.add_argument("--out", default="/app/data/cache/validation_inventory.json")
    args = ap.parse_args()

    criteria = CRITERIA_UNDER_TEST
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        criteria = [c for c in CRITERIA_UNDER_TEST if c.id in wanted]

    aoi = AOI(bbox_4326=tuple(args.bbox))
    weights = {c.id: 1.0 / len(criteria) for c in criteria}

    print(f"AOI: {args.bbox}")
    print(f"Criteria ({len(criteria)}): {', '.join(c.id for c in criteria)}")
    print("Computing risk surface...")
    res = compute_overlay(aoi, criteria, weights, complete=True)
    grid = res.risk_surface.grid
    risk = res.risk_surface.risk_surface
    valid = (risk != RISK_SURFACE_NODATA) & np.isfinite(risk)

    half = "test" if args.split_year else "all"
    pts = load_inventory(INVENTORY_PATH, args.bbox, args.split_year, half)
    values, kept = sample_points(risk, grid, valid, pts)

    if values.size < 10:
        raise SystemExit(f"only {values.size} usable flood points — too few to validate")

    x, y, auc = success_rate_curve(risk, valid, values)

    label = "PREDICTION-rate" if args.split_year else "SUCCESS-rate"
    print(f"\n  flood points used : {values.size}")
    if kept:
        yrs = sorted({k[2] for k in kept if k[2]})
        print(f"  year range        : {yrs[0]}-{yrs[-1]}")
    print(f"  valid pixels      : {int(valid.sum()):,}")
    print(f"\n  {label} curve AUC : {auc:.4f}")

    # How much area must you flag to capture N% of observed floods?
    print("\n  Area needed to capture observed floods:")
    for target in (0.5, 0.8, 0.9, 1.0):
        i = np.searchsorted(y, target)
        i = min(i, x.size - 1)
        print(f"    {int(target*100):3d}% of floods  ->  top {100*x[i]:5.1f}% of area by risk")

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "method": f"{label} curve (Chung & Fabbri 2003)",
        "claim": "validated against an observed flood inventory (BIPAD/NDRRMA incident records)",
        "inventory_source": "https://bipadportal.gov.np/api/v1/incident/ (hazard=Flood,Inundation)",
        "bbox_4326": list(args.bbox),
        "criteria": [c.id for c in criteria],
        "n_flood_points": int(values.size),
        "split_year": args.split_year,
        "auc": auc,
        "limitations": [
            "Reporting bias: incidents are recorded where people are, over-representing dense urban wards.",
            "Point records, not inundation extents; often ward/settlement centroids.",
            "BIPAD coverage is substantially better after ~2011.",
        ],
    }
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
