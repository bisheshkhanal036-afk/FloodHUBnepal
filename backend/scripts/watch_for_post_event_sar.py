"""Watch for the first post-event Sentinel-1 scene over an area, and
report the matching pre-event baseline to pair it with.

WHY A WATCHER RATHER THAN JUST RUNNING map_flood_extent.py
==========================================================
Sentinel-1 cannot be tasked. It flies a fixed 12-day repeat, so after a
disaster you wait for the next pass over that specific spot, and then
wait again for the RTC product to be processed and published (typically
1-3 more days). For the 26 Aug 2026 Rasuwa GLOF, checked the day after
the event, the newest available scene was still two days BEFORE the
flood.

This script answers "is it there yet, and what should I pair it with"
without a human re-deriving the orbit arithmetic each time.

THE ORBIT-PAIRING RULE THIS ENCODES
===================================
Backscatter depends heavily on viewing geometry -- incidence angle,
look direction, and how the terrain sits relative to the sensor. In
mountains that dependence is severe. Comparing a descending-pass scene
against an ascending-pass one produces differences that have nothing to
do with flooding and can easily exceed the flood signal.

So the pre-event baseline must come from the **same relative orbit and
the same pass direction** as the post-event scene. This script finds the
most recent qualifying pre-event scene automatically rather than letting
someone pair 24 Aug (orbit 19, descending) with 28 Aug (orbit 85,
ascending) and trust the result.

WORKED EXAMPLE -- Rasuwa, checked 2026-08-27
============================================
    orbit  85 ascending : ...23 Jul, 04 Aug, 16 Aug -> next 28 Aug 12:21
    orbit 121 descending: ...26 Jul, 07 Aug, 19 Aug -> next 31 Aug 00:10
    orbit  19 descending: ...31 Jul, 12 Aug, 24 Aug -> next 05 Sep 00:18

First post-event acquisition is orbit 85, and its correct baseline is
16 Aug -- NOT the more recent 24 Aug, which is a different orbit.

USAGE
=====
    # one check
    python watch_for_post_event_sar.py --bbox 85.28 28.10 85.45 28.32 \\
        --event 2026-08-26T09:00

    # poll until it appears, then print the exact command to run
    python watch_for_post_event_sar.py --bbox 85.28 28.10 85.45 28.32 \\
        --event 2026-08-26T09:00 --poll 3600

Exit code is 0 when a post-event scene is available, 1 when not -- so it
can drive a shell loop or CI step.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
COLLECTION = "sentinel-1-rtc"
REPEAT_DAYS = 12  # Sentinel-1 ground-track repeat cycle


def search(bbox, start: datetime, end: datetime) -> list[dict]:
    body = json.dumps({
        "collections": [COLLECTION],
        "bbox": list(bbox),
        "datetime": f"{start.isoformat()[:19]}Z/{end.isoformat()[:19]}Z",
        "limit": 100,
    }).encode()
    req = urllib.request.Request(STAC_SEARCH, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        feats = json.load(r)["features"]
    feats.sort(key=lambda f: f["properties"]["datetime"])
    return feats


def _key(item: dict) -> tuple:
    """The geometry identity a valid pre/post pair must share."""
    p = item["properties"]
    return (p.get("sat:relative_orbit"), p.get("sat:orbit_state"))


def check(bbox, event: datetime, quiet: bool = False) -> dict | None:
    feats = search(bbox, event - timedelta(days=40), event + timedelta(days=40))
    if not feats:
        print("no RTC scenes at all for this bbox")
        return None

    pre = [f for f in feats if f["properties"]["datetime"] < event.isoformat()]
    post = [f for f in feats if f["properties"]["datetime"] >= event.isoformat()]

    if not quiet:
        print(f"scenes found: {len(pre)} pre-event, {len(post)} post-event")

    if not post:
        if not quiet:
            # Project the next pass per orbit so the wait is quantified.
            latest: dict[tuple, datetime] = {}
            for f in pre:
                dt = datetime.fromisoformat(f["properties"]["datetime"][:19]).replace(tzinfo=timezone.utc)
                k = _key(f)
                if k not in latest or dt > latest[k]:
                    latest[k] = dt
            now = datetime.now(timezone.utc)
            print("\nno post-event scene yet. Projected next passes:")
            for (orbit, state), dt in sorted(latest.items(), key=lambda kv: kv[1] + timedelta(days=REPEAT_DAYS)):
                nxt = dt + timedelta(days=REPEAT_DAYS)
                print(f"  orbit {str(orbit):>4} {state:<11} last {dt.isoformat()[:16]}"
                      f"  -> next ~{nxt.isoformat()[:16]}"
                      f"  ({(nxt - now).total_seconds() / 86400:+.1f} days)")
            print("\n  Add 1-3 days on top for RTC processing/publication latency.")
        return None

    first = post[0]
    fkey = _key(first)
    # The most recent pre-event scene sharing orbit AND pass direction.
    same = [f for f in pre if _key(f) == fkey]

    result = {
        "post": first["properties"]["datetime"][:19],
        "post_id": first["id"],
        "orbit": fkey[0],
        "pass": fkey[1],
        "pre": same[-1]["properties"]["datetime"][:19] if same else None,
    }

    print("\n*** POST-EVENT SCENE AVAILABLE ***")
    print(f"  post : {result['post']}  orbit={result['orbit']} {result['pass']}")
    if result["pre"]:
        print(f"  pre  : {result['pre']}  (same orbit + pass -- correct baseline)")
        print("\nRun:")
        print(f"  python /app/map_flood_extent.py \\\n"
              f"    --pre {result['pre'][:10]} --post {result['post'][:10]} \\\n"
              f"    --bbox {' '.join(str(b) for b in bbox)} \\\n"
              f"    --out /app/data/cache/flood_extent_{result['post'][:10]}.tif")
    else:
        print(f"  WARNING: no pre-event scene on orbit {result['orbit']} {result['pass']}.")
        print("  Pairing across different orbits is unreliable in mountainous terrain "
              "-- prefer waiting for the next same-orbit pass.")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("MINX", "MINY", "MAXX", "MAXY"))
    ap.add_argument("--event", required=True,
                    help="event time, ISO e.g. 2026-08-26T09:00")
    ap.add_argument("--poll", type=int, default=0,
                    help="seconds between checks; 0 = check once and exit")
    args = ap.parse_args()

    event = datetime.fromisoformat(args.event).replace(tzinfo=timezone.utc)
    bbox = tuple(args.bbox)

    while True:
        print(f"\n[{datetime.now(timezone.utc).isoformat()[:19]}Z] checking {bbox}")
        try:
            got = check(bbox, event)
        except Exception as exc:  # noqa: BLE001 - a transient API failure must not kill a long poll
            print(f"  check failed ({exc}); will retry")
            got = None
        if got:
            return 0
        if not args.poll:
            return 1
        time.sleep(args.poll)


if __name__ == "__main__":
    sys.exit(main())
