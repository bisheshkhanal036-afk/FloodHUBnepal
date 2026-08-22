# Pre-processed Nepal OSM extracts

`buildings.fgb`, `roads.fgb`, `waterways.fgb` — geometry-only
[FlatGeobuf](https://flatgeobuf.org/) files, EPSG:4326, one per feature
type, built from the Geofabrik shapefile export in the parent
`nepal-260713-free.shp/` directory (not from the raw `.osm.pbf` — the
shapefiles are already split by feature type and already resolved
geometries, so this avoids pyrosm's much heavier OSM-primitive
resolution step entirely). See `app/data/config.py`'s
`LOCAL_OSM_PROCESSED_DIR` docstring for why this exists and the real
speed numbers.

Not tracked in git (large binaries, and — like the raw `.pbf`/shapefile
sources next to them — regenerable from a fresh Geofabrik download, not
themselves a source of truth). Regenerate with:

```python
import pyogrio

SRC = "../nepal-260713-free.shp"  # the Geofabrik shapefile export
NON_DRIVING_FCLASS = {  # excluded from "roads" -- mirrors pyrosm's network_type="driving" intent
    "path", "footway", "steps", "pedestrian", "cycleway", "bridleway",
    "track", "track_grade1", "track_grade2", "track_grade3", "track_grade4", "track_grade5",
    "unknown",
}
WATERWAY_FCLASS = {"river", "stream", "canal"}  # matches osm.py's WATERWAY_TAGS exactly

def build(name, shp_filename, keep_fn=None):
    columns = ["fclass"] if keep_fn else []
    df = pyogrio.read_dataframe(f"{SRC}/{shp_filename}", columns=columns, read_geometry=True)
    if keep_fn is not None:
        df = df[df["fclass"].apply(keep_fn)].drop(columns=["fclass"])
    pyogrio.write_dataframe(df, f"{name}.fgb", driver="FlatGeobuf", spatial_index=True)

build("waterways", "gis_osm_waterways_free_1.shp", keep_fn=lambda v: v in WATERWAY_FCLASS)
build("roads", "gis_osm_roads_free_1.shp", keep_fn=lambda v: v not in NON_DRIVING_FCLASS)
build("buildings", "gis_osm_buildings_a_free_1.shp")  # no filter -- every building counts for density
```

Run this on the **host** Python, not inside Docker — it's a one-time
offline data-prep step with no dependency on the `app` package, and the
buildings step (8.26M features nationwide) needs more memory headroom
than Docker Desktop's default WSL2 limit gives the container (this was
tried inside the container first and got OOM-killed at 6.7GB; the host
here has ~14GB and handled it in under 2 minutes). Only geometry is
kept in every file — every consumer (`density_raster.py`,
`distance_raster.py`) only ever reads `.geometry`, so attribute columns
would only inflate the output for no benefit.

Building the buildings extract also needs real free disk headroom for
the output (~1.9GB) — this was attempted once with only ~4GB free and
had to be aborted mid-write; re-run with at least 10-15GB free.
