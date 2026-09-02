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

---

## `attributed/` — the same OSM, but with tags

The three files above are **geometry-only**, which is right for the
criterion sources that read them (`density_raster.py` and
`distance_raster.py` only ever touch `.geometry`) and is what keeps the
nationwide buildings extract manageable.

It also means they cannot answer any question about *what* a feature is.
After the 26 August 2026 Rasuwa flood we could not ask our own data
"which hydropower facilities are in the flood corridor" or "how many
residential buildings are exposed", because `buildings.fgb` has exactly
one column and there was no power extract at all.

`backend/scripts/extract_osm_attributes.py` writes attribute-bearing
files into `attributed/` **without touching the geometry-only ones**:

| File | Contents |
|---|---|
| `power.fgb` | `power=*` infrastructure with `name`, `operator`, `plant:source`, output capacity |
| `buildings.fgb` | footprints with their `building` type and `building:levels` |
| `roads.fgb` | highways with `highway` class, `bridge`, `surface` |
| `amenities.fgb` | schools, hospitals, clinics, police, shelters — exposure receptors |

Regenerate (bbox strongly recommended for anything but `power`):

```bash
docker cp backend/scripts/extract_osm_attributes.py \
  floodhubnepal-main-backend-1:/app/extract_osm_attributes.py
docker compose exec -T backend python /app/extract_osm_attributes.py \
  --theme power --bbox 85.0 27.9 86.0 28.5
```

### Two things worth knowing before relying on this

**pyrosm is not usable for this.** It has no spatial index into the
`.pbf` and decodes the whole file regardless of the bbox requested —
measured here as **not finishing in 10 minutes** for a single district.
GDAL's OSM driver (via pyogrio) reads the same file's metadata in 0.4 s
and streams a bbox-limited `points` read in ~15 s. The extraction script
uses pyogrio throughout for that reason.

**OSM's `power=plant` tag is unreliable in this extract.** In the
Rasuwa/Langtang bbox, 21 features carry `power=plant` and most are
trekking lodges ("Nima Hotel", "Everest Guest House", "Hotel Yala
Peak"). The genuine hydropower is tagged `power=generator` instead.
Coverage is also incomplete: of the facilities reported damaged on
26 Aug 2026, OSM has Chilime and Trishuli, ambiguous name-matches for
several more, and **nothing at all** for Rasuwagadhi. Treat this as a
partial, noisy inventory — useful for locating what it has, never as an
authoritative asset register.
