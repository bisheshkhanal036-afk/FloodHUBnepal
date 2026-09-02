"""Re-extract OSM features from the raw .pbf **with their attributes**,
alongside the existing geometry-only extracts.

WHY THIS EXISTS
===============
`backend/data/raw/osm/processed/{buildings,roads,waterways}.fgb` are
geometry-only by design -- see that directory's README. That is exactly
right for the criterion sources that consume them (`density_raster.py`
and `distance_raster.py` only ever read `.geometry`), and stripping
attributes keeps the nationwide buildings extract manageable.

But it makes a whole class of question unanswerable. After the 26 August
2026 Rasuwa flood we could not use our own data to ask "which hydropower
facilities are in the flood corridor" or "how many *residential*
buildings are exposed", because `buildings.fgb` has literally one column
(`geometry`) and there is no power-infrastructure extract at all.

This script fills that gap without touching the existing extracts: it
writes *separate*, attribute-bearing files that exposure analysis can
use, while every existing criterion source keeps reading the fast
geometry-only ones unchanged.

WHY GDAL/pyogrio AND NOT pyrosm
================================
`app/data/osm.py` uses pyrosm for its own .pbf fallback and documents
that parsing a full Nepal extract is expensive. Measured here, it is
worse than that: **pyrosm did not finish in 10 minutes even with a
bounding box**, because it has no spatial index into the .pbf and
decodes the whole file regardless of the bbox requested.

GDAL's OSM driver (via pyogrio) reads the same file's metadata in 0.4 s
and streams a bbox-limited read of the `points` layer in ~15 s. Every
extraction below therefore goes through pyogrio.

Trade-off to be aware of: GDAL's OSM driver puts any tag that is not one
of its configured "primary" fields into a single `other_tags` HSTORE
string (`"power"=>"generator","operator"=>"NEA"`). `_tag()` below parses
values back out of it. That is why the filters here match on
`other_tags` rather than on real columns.

WHAT IT PRODUCES
================
Written to `backend/data/raw/osm/processed/attributed/`:

  power.fgb      power=* infrastructure (plants, generators, substations,
                 towers, lines) from points/lines/multipolygons
  buildings.fgb  building footprints WITH their `building` type tag
  roads.fgb      highways WITH `highway` class and `bridge` flag
  amenities.fgb  schools, hospitals, clinics -- the exposure receptors
                 a flood report actually cares about

All are gitignored like everything else under `backend/data/`, and are
regenerable from the .pbf at any time.

DATA-QUALITY WARNING FOUND WHILE BUILDING THIS
==============================================
OSM's `power=plant` tag is **not reliable** in this extract. In the
Rasuwa/Langtang bbox, 21 features carry `power=plant` and most of them
are trekking lodges -- "Nima Hotel", "Everest Guest House", "Hotel Yala
Peak". The genuine hydropower facilities that were damaged are tagged
`power=generator` instead (Chilime Hydro Power Plant; Trishuli
Hydropower Station).

Coverage is also incomplete: of the facilities reported damaged on
26 Aug 2026, OSM has Chilime and Trishuli, has name-matches of uncertain
type for several others, and has **no feature at all** matching
Rasuwagadhi. Anything built on this must treat OSM power data as a
partial, noisy inventory -- useful for locating what it does have, never
as an authoritative asset register.

USAGE
=====
    docker cp backend/scripts/extract_osm_attributes.py \\
      floodhubnepal-main-backend-1:/app/extract_osm_attributes.py
    docker compose exec -T backend python /app/extract_osm_attributes.py --theme power
    docker compose exec -T backend python /app/extract_osm_attributes.py --theme all --bbox 85.0 27.9 86.0 28.5

Nationwide `buildings` is the expensive one (8.26M features; the
README documents an earlier attempt being OOM-killed at 6.7 GB inside
this container). Pass `--bbox` for anything district-scale, and prefer
running the nationwide buildings pass on the host.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

PBF = Path("/app/data/raw/osm/nepal-260821.osm.pbf")
OUT_DIR = Path("/app/data/raw/osm/processed/attributed")

# Nepal, per basins.py's own NEPAL_BBOX_4326.
NEPAL_BBOX = (80.0, 26.3, 88.3, 30.5)

_TAG_RE = {}


def _tag(other_tags: str | None, key: str) -> str | None:
    """Pull one value out of GDAL's `other_tags` HSTORE string.

    Format is `"key"=>"value","key2"=>"value2"`. Regexes are cached per
    key since this runs once per feature per key over millions of rows.
    """
    if not other_tags:
        return None
    rx = _TAG_RE.get(key)
    if rx is None:
        rx = _TAG_RE[key] = re.compile(r'"%s"=>"([^"]*)"' % re.escape(key))
    m = rx.search(other_tags)
    return m.group(1) if m else None


def _read(layer: str, bbox) -> gpd.GeoDataFrame | None:
    t0 = time.time()
    try:
        df = pyogrio.read_dataframe(PBF, layer=layer, bbox=bbox)
    except Exception as exc:  # noqa: BLE001 - layer may be absent/unreadable
        print(f"  {layer:16s} ERROR {str(exc)[:80]}")
        return None
    print(f"  {layer:16s} {len(df):>8,} features in {time.time() - t0:5.1f}s")
    return df


def _write(gdf: gpd.GeoDataFrame, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.fgb"
    if gdf.empty:
        print(f"  -> {name}: nothing to write")
        return
    # Drop all-null columns: GDAL emits many primary fields that are
    # empty for most themes, and they only bloat the output.
    gdf = gdf.dropna(axis=1, how="all")
    gdf.to_file(path, driver="FlatGeobuf", spatial_index=True)
    mb = path.stat().st_size / 1e6
    print(f"  -> {name}.fgb  {len(gdf):,} features, {mb:.1f} MB, cols={list(gdf.columns)}")


def extract_power(bbox) -> None:
    """power=* infrastructure.

    Kept across points/lines/multipolygons because OSM maps power assets
    inconsistently: generators as nodes, transmission as ways, plant
    grounds as areas. See the module docstring on why `power=plant`
    cannot be trusted on its own.
    """
    print("\n[power]")
    frames = []
    for layer in ("points", "lines", "multipolygons"):
        df = _read(layer, bbox)
        if df is None or "other_tags" not in df.columns:
            continue
        hit = df[df["other_tags"].notna() & df["other_tags"].str.contains('"power"', na=False)].copy()
        if hit.empty:
            continue
        hit["power"] = hit["other_tags"].apply(lambda s: _tag(s, "power"))
        hit["operator"] = hit["other_tags"].apply(lambda s: _tag(s, "operator"))
        hit["plant_source"] = hit["other_tags"].apply(lambda s: _tag(s, "plant:source"))
        hit["plant_output"] = hit["other_tags"].apply(
            lambda s: _tag(s, "plant:output:electricity") or _tag(s, "generator:output:electricity")
        )
        hit["osm_layer"] = layer
        keep = [c for c in ("osm_id", "name", "power", "operator", "plant_source",
                            "plant_output", "osm_layer", "geometry") if c in hit.columns]
        frames.append(hit[keep])
        print(f"     power-tagged: {len(hit):,}")
    if frames:
        _write(gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326"), "power")


def extract_buildings(bbox) -> None:
    """Building footprints with their `building` type.

    `building` IS a GDAL primary field for multipolygons, so no
    other_tags parsing is needed for the type itself.
    """
    print("\n[buildings]")
    df = _read("multipolygons", bbox)
    if df is None or "building" not in df.columns:
        return
    hit = df[df["building"].notna()].copy()
    if "other_tags" in hit.columns:
        hit["levels"] = hit["other_tags"].apply(lambda s: _tag(s, "building:levels"))
    keep = [c for c in ("osm_id", "name", "building", "levels", "geometry") if c in hit.columns]
    _write(hit[keep], "buildings")


def extract_roads(bbox) -> None:
    """Highways with class and bridge flag.

    `bridge` matters for flood work specifically -- bridges are both the
    most flood-vulnerable road asset and the ones whose loss cuts access.
    """
    print("\n[roads]")
    df = _read("lines", bbox)
    if df is None or "highway" not in df.columns:
        return
    hit = df[df["highway"].notna()].copy()
    if "other_tags" in hit.columns:
        hit["bridge"] = hit["other_tags"].apply(lambda s: _tag(s, "bridge"))
        hit["surface"] = hit["other_tags"].apply(lambda s: _tag(s, "surface"))
    keep = [c for c in ("osm_id", "name", "highway", "bridge", "surface", "geometry") if c in hit.columns]
    _write(hit[keep], "roads")


def extract_amenities(bbox) -> None:
    """Schools, hospitals and clinics -- exposure receptors.

    These are what an exposure report should count, not just "buildings":
    a flooded hospital or school is a materially different finding from a
    flooded shed.
    """
    print("\n[amenities]")
    wanted = {"school", "hospital", "clinic", "doctors", "college", "university",
              "police", "fire_station", "shelter"}
    frames = []
    for layer in ("points", "multipolygons"):
        df = _read(layer, bbox)
        if df is None or "other_tags" not in df.columns:
            continue
        hit = df[df["other_tags"].notna() & df["other_tags"].str.contains('"amenity"', na=False)].copy()
        if hit.empty:
            continue
        hit["amenity"] = hit["other_tags"].apply(lambda s: _tag(s, "amenity"))
        hit = hit[hit["amenity"].isin(wanted)]
        if hit.empty:
            continue
        hit["osm_layer"] = layer
        keep = [c for c in ("osm_id", "name", "amenity", "osm_layer", "geometry") if c in hit.columns]
        frames.append(hit[keep])
        print(f"     matching amenities: {len(hit):,}")
    if frames:
        _write(gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326"), "amenities")


THEMES = {
    "power": extract_power,
    "buildings": extract_buildings,
    "roads": extract_roads,
    "amenities": extract_amenities,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--theme", default="power", choices=[*THEMES, "all"])
    ap.add_argument("--bbox", nargs=4, type=float, default=None,
                    metavar=("MINX", "MINY", "MAXX", "MAXY"),
                    help="Limit extraction. Default: all Nepal (slow for buildings).")
    args = ap.parse_args()

    if not PBF.exists():
        raise SystemExit(f"OSM extract not found at {PBF}")

    bbox = tuple(args.bbox) if args.bbox else NEPAL_BBOX
    themes = list(THEMES) if args.theme == "all" else [args.theme]

    print(f"source: {PBF.name}")
    print(f"bbox  : {bbox}")
    print(f"themes: {', '.join(themes)}")

    t0 = time.time()
    for name in themes:
        THEMES[name](bbox)
    print(f"\ndone in {time.time() - t0:.1f}s -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
