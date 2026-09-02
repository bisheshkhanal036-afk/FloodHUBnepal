"""Map OBSERVED flood extent from Sentinel-1 SAR change detection.

WHY THIS EXISTS
===============
Everything else in this project predicts where flooding *tends* to
happen. Nothing in it could say where water *actually went* during a
specific event. After the 26 August 2026 Rasuwa GLOF we could show a
susceptibility surface but not an observed flood extent -- and those are
completely different products that must never be conflated.

This closes that gap using the standard remote-sensing method: radar
sees through cloud (essential during monsoon, when optical imagery is
useless), and open water is a near-specular reflector that scatters
energy away from the sensor, so flooded ground appears as a sharp drop
in backscatter relative to a pre-event baseline.

DATA SOURCE, AND WHY THIS ONE
=============================
Microsoft Planetary Computer's `sentinel-1-rtc` collection:
**Radiometrically Terrain Corrected** gamma0, as Cloud-Optimized
GeoTIFFs, searchable via STAC and readable with a free, unauthenticated
SAS token.

RTC specifically, not plain GRD, because this project's study areas are
mountainous. Raw GRD backscatter in a Himalayan gorge is dominated by
terrain effects -- a slope facing the sensor is bright and one facing
away is dark regardless of what is on the ground. RTC normalises that
out. Doing the equivalent ourselves would mean running SNAP/ESA
toolboxes, which is a far heavier dependency than this project should
take on for an analysis script.

Verified live during implementation: scene opens in 1.4 s, 27750x21837
float32, EPSG:32645 (the same UTM zone our own grid uses for this
region), properly tiled with overviews [2,4,8,16,32,64]; a windowed read
over the Bhote Koshi corridor took ~31 s.

THE METHOD
==========
Flood is detected as the intersection of two conditions, not either one
alone:

  1. **Low backscatter now** -- post-event gamma0 below WATER_DB.
     Necessary but nowhere near sufficient: dry sand, smooth tarmac,
     and radar shadow are all dark too.

  2. **A real drop from before** -- (pre_dB - post_dB) exceeds
     CHANGE_DB. This is what separates *newly* flooded ground from
     things that were always dark, including permanent water bodies,
     which correctly do NOT get reported as flood.

Requiring both is what makes the result about *this event* rather than
about surface type.

TERRAIN MASKING -- reusing our own layers
=========================================
SAR flood mapping in steep terrain has a well-known failure mode: radar
shadow behind ridges produces near-zero backscatter that looks exactly
like calm water. RTC reduces but does not remove this.

Rather than accept those false positives, two masks are applied from
layers this project already computes for its criterion sources:

  * **Slope** (`app/data/dem.py`) -- water does not stand on a steep
    face. Anything above MAX_SLOPE_DEG is rejected.
  * **HAND** (`app/data/hydrology.py`) -- Height Above Nearest Drainage.
    Floodwater cannot sit far above the local drainage network, so
    anything above MAX_HAND_M is rejected. This is physically motivated,
    and HAND was independently measured to be this project's strongest
    real flood predictor (flood points median 2.5 m vs 23.6 m
    valley-wide -- see METEOR_VALIDATION_RESULTS.md Part 2).

That reuse is the point: the terrain understanding built for prediction
is exactly what a SAR observation needs to stay honest.

WHAT THIS IS NOT
================
* Not real-time. Sentinel-1 revisit over Nepal is several days, and
  scenes appear in the archive hours after acquisition. Checked the day
  after the Rasuwa event: the newest scene was still two days *before*
  the flood.
* Not validated. The thresholds below are literature-conventional
  starting points, NOT calibrated against Nepali ground truth. Treat
  output as indicative until checked against an independent extent
  (Copernicus EMS, or field reports).
* Not a damage assessment. It maps water, not harm.

USAGE
=====
    # validation: two PRE-event scenes, same orbit -> expect ~no flood
    python map_flood_extent.py --pre 2026-08-12 --post 2026-08-24 \\
        --bbox 85.28 28.10 85.45 28.32

    # real use, once a post-event scene exists
    python map_flood_extent.py --pre 2026-08-24 --post 2026-08-29 \\
        --bbox 85.28 28.10 85.45 28.32 --out /app/data/cache/rasuwa_flood.tif

Pairing scenes from the same relative orbit matters -- viewing geometry
changes backscatter enough to swamp the flood signal otherwise. The
script warns when the chosen pair's orbits differ.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject, transform_bounds

from app.data.aoi import AOI
from app.data.dem import get_dem
from app.data.grid import compute_aoi_grid
from app.data.hydrology import get_hand

STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-1-rtc"
COLLECTION = "sentinel-1-rtc"

# --- detection thresholds -------------------------------------------------
# Conventional starting values from the SAR flood-mapping literature.
# NOT calibrated for Nepal. Exposed as CLI flags precisely because they
# should be tuned once an independent reference extent exists.

# Post-event gamma0 below this is "dark enough to possibly be water".
WATER_DB = -15.0

# Required drop from pre to post, in dB, for the change to count as real
# rather than speckle. Sentinel-1 speckle on a single look is roughly
# 1-2 dB, so 3 dB is a deliberately conservative floor.
CHANGE_DB = 3.0

# Terrain rejection (see module docstring).
MAX_SLOPE_DEG = 15.0
MAX_HAND_M = 25.0

# Below this, gamma0 is treated as no-data rather than "very dark".
MIN_VALID_GAMMA0 = 1e-6


def _sas_token() -> str:
    with urllib.request.urlopen(SAS_TOKEN, timeout=60) as r:
        return json.load(r)["token"]


def _search(bbox, start: str, end: str) -> list[dict]:
    body = json.dumps({
        "collections": [COLLECTION],
        "bbox": list(bbox),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": 50,
    }).encode()
    req = urllib.request.Request(STAC_SEARCH, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)["features"]


def _pick(features: list[dict], date: str) -> dict:
    """The scene whose acquisition date matches `date` (YYYY-MM-DD)."""
    same = [f for f in features if f["properties"]["datetime"].startswith(date)]
    if not same:
        have = sorted({f["properties"]["datetime"][:10] for f in features})
        raise SystemExit(f"no scene on {date}. Available: {have}")
    return same[0]


def _read_on_grid(item: dict, token: str, grid, polarization: str) -> np.ndarray:
    """One scene's gamma0, windowed-read and reprojected onto `grid`.

    Bilinear, matching how every other continuous raster in this project
    is resampled (SPEC.md 2.2). Returns NaN where the source had nodata.
    """
    url = "/vsicurl/" + item["assets"][polarization]["href"] + "?" + token
    dest = np.full((grid.height, grid.width), np.nan, dtype=np.float32)

    with rasterio.Env(GDAL_HTTP_TIMEOUT=300, GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(url) as ds:
            left, bottom, right, top = transform_bounds(
                grid.crs, ds.crs,
                grid.origin_x, grid.origin_y - grid.height * grid.resolution_m,
                grid.origin_x + grid.width * grid.resolution_m, grid.origin_y,
            )
            window = rasterio.windows.from_bounds(left, bottom, right, top, transform=ds.transform)
            window = window.round_lengths().round_offsets()
            # Pad so bilinear resampling at the edge has real neighbours.
            pad = rasterio.windows.Window(
                max(window.col_off - 2, 0), max(window.row_off - 2, 0),
                min(window.width + 4, ds.width - max(window.col_off - 2, 0)),
                min(window.height + 4, ds.height - max(window.row_off - 2, 0)),
            )
            src = ds.read(1, window=pad).astype(np.float32)
            src_transform = ds.window_transform(pad)
            src_nodata = ds.nodata

            if src_nodata is not None:
                src[src == src_nodata] = np.nan
            src[src < MIN_VALID_GAMMA0] = np.nan

            reproject(
                source=src, destination=dest,
                src_transform=src_transform, src_crs=ds.crs, src_nodata=np.nan,
                dst_transform=grid.transform, dst_crs=grid.crs, dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
    return dest


def _to_db(gamma0: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10.0 * np.log10(gamma0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("MINX", "MINY", "MAXX", "MAXY"))
    ap.add_argument("--pre", required=True, help="pre-event date YYYY-MM-DD")
    ap.add_argument("--post", required=True, help="post-event date YYYY-MM-DD")
    ap.add_argument("--polarization", default="vv", choices=("vv", "vh"))
    ap.add_argument("--water-db", type=float, default=WATER_DB)
    ap.add_argument("--change-db", type=float, default=CHANGE_DB)
    ap.add_argument("--max-slope", type=float, default=MAX_SLOPE_DEG)
    ap.add_argument("--max-hand", type=float, default=MAX_HAND_M)
    ap.add_argument("--no-terrain-mask", action="store_true",
                    help="skip slope/HAND masking, to see raw SAR change")
    ap.add_argument("--out", default=None, help="write flood mask GeoTIFF here")
    args = ap.parse_args()

    bbox = tuple(args.bbox)
    aoi = AOI(bbox_4326=bbox)
    grid = compute_aoi_grid(aoi.bounds_utm)
    print(f"AOI  : {bbox}")
    print(f"grid : {grid.width}x{grid.height} @ {grid.resolution_m}m {grid.crs}")

    # widen the search window so a nearby scene is findable
    feats = _search(bbox, args.pre, args.post)
    if not feats:
        raise SystemExit("no Sentinel-1 RTC scenes found for that bbox/date range")
    print(f"\nRTC scenes in range: {len(feats)}")
    for f in feats:
        p = f["properties"]
        print(f"  {p['datetime'][:19]}  orbit={p.get('sat:relative_orbit')}  "
              f"pass={p.get('sat:orbit_state')}")

    pre_item, post_item = _pick(feats, args.pre), _pick(feats, args.post)
    o_pre = pre_item["properties"].get("sat:relative_orbit")
    o_post = post_item["properties"].get("sat:relative_orbit")
    print(f"\npre : {pre_item['properties']['datetime'][:19]} orbit={o_pre}")
    print(f"post: {post_item['properties']['datetime'][:19]} orbit={o_post}")
    if o_pre != o_post:
        print("  WARNING: different relative orbits -- viewing geometry differs, and "
              "that difference can swamp the flood signal. Prefer a same-orbit pair.")

    token = _sas_token()
    print(f"\nreading {args.polarization.upper()}...")
    pre = _read_on_grid(pre_item, token, grid, args.polarization)
    post = _read_on_grid(post_item, token, grid, args.polarization)

    pre_db, post_db = _to_db(pre), _to_db(post)
    valid = np.isfinite(pre_db) & np.isfinite(post_db)
    print(f"  valid pixels in both scenes: {int(valid.sum()):,} "
          f"({100 * valid.mean():.1f}% of grid)")
    if valid.sum() == 0:
        raise SystemExit("no overlapping valid pixels")

    drop = pre_db - post_db
    is_dark = post_db < args.water_db
    is_drop = drop > args.change_db
    flood = valid & is_dark & is_drop

    print(f"\n  dark now      (< {args.water_db} dB) : {int((valid & is_dark).sum()):,}")
    print(f"  dropped       (> {args.change_db} dB) : {int((valid & is_drop).sum()):,}")
    print(f"  both (candidate flood)          : {int(flood.sum()):,}")

    if not args.no_terrain_mask:
        slope = get_dem(aoi).slope_degrees
        hand = get_hand(aoi).hand
        steep = slope > args.max_slope
        high = hand > args.max_hand
        rejected_steep = int((flood & steep).sum())
        rejected_high = int((flood & high & ~steep).sum())
        flood = flood & ~steep & ~high
        print(f"\n  terrain mask (slope <= {args.max_slope} deg, HAND <= {args.max_hand} m):")
        print(f"    rejected as too steep       : {rejected_steep:,}")
        print(f"    rejected as too high above drainage: {rejected_high:,}")

    n = int(flood.sum())
    area_km2 = n * (grid.resolution_m ** 2) / 1e6
    pct = 100.0 * n / max(int(valid.sum()), 1)
    print(f"\n  FLOODED: {n:,} px = {area_km2:.2f} km^2 ({pct:.2f}% of valid area)")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            out, "w", driver="GTiff", height=grid.height, width=grid.width,
            count=1, dtype="uint8", crs=grid.crs, transform=grid.transform,
            nodata=255, compress="deflate",
        ) as dst:
            band = np.where(valid, flood.astype(np.uint8), 255).astype(np.uint8)
            dst.write(band, 1)
            dst.update_tags(
                pre_scene=pre_item["id"], post_scene=post_item["id"],
                water_db=str(args.water_db), change_db=str(args.change_db),
                terrain_masked=str(not args.no_terrain_mask),
                generated=datetime.now(timezone.utc).isoformat(),
                note="1=flood, 0=not flood, 255=nodata. Indicative, thresholds uncalibrated.",
            )
        print(f"  wrote {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
