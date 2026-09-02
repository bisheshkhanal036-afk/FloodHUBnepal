# SPEC — Flood Risk Mapping & Shelter Identification, Kathmandu Valley

Status: **Backend (AHP engine, geospatial data layer with 14 registered
criterion sources, overlay engine, vulnerability-classification/reporting,
shelter-site identification) and a working, redesigned frontend map UI
implemented** — see §5. This document defines
the shared data contracts and project-wide conventions that every phase
(backend, frontend, analysis pipeline) must follow.

## 1. Repository layout

```
/backend    FastAPI service (Python) — API, AHP computation, raster overlay
/frontend   React + MapLibre GL client
/schemas    JSON Schema data contracts, shared source of truth for both sides
SPEC.md     this document
docker-compose.yml   local dev stack: PostGIS + backend + frontend, localhost-only
```

The contents of `/schemas` are the single source of truth for the shapes
described below. Backend Pydantic models and frontend TypeScript/JS types
should be generated from, or kept in lockstep with, these files — not
redefined independently.

## 2. Project-wide conventions

### 2.1 CRS convention

- **EPSG:4326** (WGS 84 lon/lat) is used for the AOI as drawn/entered by the
  user, and for all API request/response bodies that carry coordinates.
- **EPSG:32645** (WGS 84 / UTM Zone 45N) is used for every calculation that
  is metric in nature: area, distance, slope, buffering, and all raster
  overlay math. Kathmandu Valley falls entirely within UTM Zone 45N.
- Data is reprojected to EPSG:32645 on the fly for calculation and the
  result translated back to EPSG:4326 only where the API contract calls for
  it. **Area, distance, and slope must never be computed directly against
  EPSG:4326 degree coordinates** — degrees are not a uniform unit of length,
  and doing so silently produces wrong numbers rather than an error.

### 2.2 Grid/resolution convention

- Every input raster is reprojected into EPSG:32645 and resampled onto a
  single common analysis grid at **10m resolution**.
- The grid's origin/alignment is derived **deterministically from the AOI**
  (not from each source raster's native alignment), so that repeated
  requests for the same AOI always produce an identical pixel grid — this is
  what makes the `RiskSurface.cache_key` scheme in §3.4 safe to rely on.
- Resampling method depends on data type, and this must not be mixed up:
  - **Continuous data** (elevation, slope, rainfall, distance surfaces) →
    **bilinear** resampling.
  - **Categorical / already-reclassified data** (land cover, discrete 1-5
    risk classes) → **nearest-neighbor** resampling only. Averaging across
    discrete category codes produces meaningless intermediate values and
    must never be used.
  - **Count-type continuous data is NOT bilinear-resampled directly.**
    Bilinear resampling is only correct for an *intensive* quantity (a
    value that doesn't scale with pixel area — elevation, slope, a
    distance) or an already-normalized density. A *count* (population
    per source pixel, building count per cell, etc.) is *extensive* — it
    scales with the area it was counted over — so resampling it directly
    from a coarser native pixel onto this grid's finer 10m pixels
    silently stops being a count at all: it neither reproduces the
    original per-area count (dividing a 30m-pixel's count by 9 to spread
    it over nine 10m pixels) nor conserves the total across the AOI.
    The correct handling: convert count → density (people/km² or
    equivalent) at the source's own native resolution FIRST, THEN
    bilinear-resample that density field onto the common grid, exactly
    like any other intensive continuous quantity. `population.py`'s
    `_count_to_density` does this (dividing by each source row's true
    geodetic pixel area, not a single fixed constant, since a WGS84
    pixel's ground area shrinks with latitude) — the reference
    implementation for any future count-type source.
- `Criterion.resampling_method` in the schema records which of the two
  applies to a given input layer.

### 2.3 Nodata handling

- Every input raster must declare an explicit, known nodata value
  (`Criterion.declared_nodata_value`) before it participates in any overlay
  math.
- Nodata values must be reconciled/consistent across all criteria in a given
  analysis before pixels are combined. Mismatched or undeclared nodata is a
  known silent-failure risk (e.g. a stray `0` or `-9999` from one layer
  bleeding into a weighted sum as if it were a real value).
- Validation must **raise a clear, actionable error** the first time
  inconsistent or missing nodata is detected — it must never be silently
  ignored, coerced, or averaged away.

## 3. Data contracts

Full field-level definitions live in `/schemas/*.schema.json`
(JSON Schema, draft 2020-12). Summarized in plain language:

### 3.1 AOI — `schemas/aoi.schema.json`

The Area of Interest a request is scoped to — either hand-drawn (a plain
bbox) or selected from a basin (§3.5). Both are the same `AOI` type and
flow through every later stage identically.

| Field | Meaning |
|---|---|
| `bbox` | `[minx, miny, maxx, maxy]` in EPSG:4326. A rectangle; width and height need not match. For a basin-derived AOI, this is the basin polygon's bounding envelope, derived automatically — never hand-specified alongside a polygon. |
| `polygon` | Optional GeoJSON Polygon/MultiPolygon, EPSG:4326. `null`/absent for a hand-drawn bbox AOI (the original, still-default case). Set to the true basin geometry for a basin-derived AOI. Every current AOI-consuming stage (DEM/WorldCover fetch, reclassification, the overlay engine) reads only `bbox`/its UTM envelope and ignores `polygon` entirely — it exists for a future consumer that needs true-shape correctness (e.g. flow accumulation for TWI/drainage density) to clip to the real shape instead of just the bbox. |
| `crs` | Always `"EPSG:4326"`. |
| `area_km2` | Server-computed area, in km², measured after reprojecting to EPSG:32645 — never computed from raw degrees. Uses the true `polygon` area when one is set (a basin is very often much smaller than its own bounding envelope), otherwise the bbox rectangle's area. |
| `max_area_km2` | Cap the AOI's area must not exceed. Default **500 km²** — enough to cover the Kathmandu Valley with headroom, while bounding per-request compute cost. Requests over the cap are rejected with a validation error, not silently clipped. Enforced once, centrally, by `backend/app/common/aoi.py`'s shared `AOIInput` request model — every endpoint that accepts an AOI (`POST /api/overlay/compute`, and basin selection via §3.5) uses this same model, so the cap applies automatically rather than being re-implemented (or forgotten) per endpoint. |

### 3.2 Criterion — `schemas/criterion.schema.json`

One input layer in the AHP model (e.g. Slope, Distance to River, Land Cover).

| Field | Meaning |
|---|---|
| `id` / `name` | Machine id and human-readable label. |
| `cluster` | One of the 5 top-level clusters: `Topographic`, `Hydrological`, `Land Use`, `Infrastructure`, `Exposure`. |
| `source_type` | `preloaded` (curated server-side layer) or `uploaded` (user-supplied). |
| `raster_source` | Path (preloaded) or URL (uploaded) to the native-resolution raster. |
| `native_resolution_m` / `native_crs` | Resolution and CRS of the source raster as delivered, before it's reprojected onto the shared 10m/EPSG:32645 grid. |
| `resampling_method` | `bilinear` for continuous data, `nearest` for categorical data — see §2.2. |
| `declared_nodata_value` | The raster's nodata sentinel, made explicit — see §2.3. |
| `reclassification_rules` | Ordered, non-overlapping, gap-free ranges mapping this criterion's native values to the 5 discrete risk classes (1 = lowest, 5 = highest). Used for legend/display, and where the model calls for a reclassified intermediate layer — **not** how the stored composite score is produced (that stays continuous, §3.4). |
| `weight` | This criterion's final AHP weight (cluster weight × within-cluster weight). `null` until an AHP run has been computed for the criteria set it belongs to. |

### 3.3 AHP Pairwise Matrix — `schemas/ahp_pairwise_matrix.schema.json`

The full AHP comparison structure for one analysis:

- `cluster_comparison` — one 5×5 matrix comparing the 5 clusters against each
  other (Saaty 1-9 scale, reciprocal off-diagonal, 1s on the diagonal).
- `within_cluster_comparisons` — one n×n matrix **per cluster**, comparing
  that cluster's member criteria against each other.
- Each matrix carries its raw judgments (`matrix`), the derived principal
  eigenvector (`weights`, normalized to sum to 1), and its consistency
  metrics (`consistency_index`, `random_index`, `consistency_ratio`).
- `final_weights` — per-criterion final weight = its cluster's weight (from
  `cluster_comparison`) × its weight within its cluster (from
  `within_cluster_comparisons[cluster]`). This is the value written back
  onto `Criterion.weight`. `within_cluster_comparisons` may legitimately
  cover fewer than all 5 clusters (e.g. while criteria are still being
  assembled), in which case `final_weights` does not sum to 1 — the
  `POST /api/ahp/compute` response carries an explicit `complete` flag
  (and `missing_clusters` list) alongside `final_weights` so a caller
  can never mistake a partial, un-normalized weight set for a finished
  one.

**Consistency ratio.** `CR = CI / RI`, where `CI = (λmax − n) / (n − 1)`
(λmax = the matrix's principal eigenvalue, n = matrix size) and `RI` is
Saaty's standard random-consistency index, looked up by matrix size:

| n | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| RI | 0.00 | 0.00 | 0.58 | 0.90 | 1.12 | 1.24 | 1.32 | 1.41 | 1.45 | 1.49 |

By convention, `CR < 0.10` is treated as an acceptably consistent set of
judgments; `CR >= 0.10` should be flagged back to whoever entered the
pairwise comparisons so they can be revisited.

### 3.4 Risk Surface — `schemas/risk_surface.schema.json`

The computed composite output for one AOI.

| Field | Meaning |
|---|---|
| `cache_key` | SHA-256 hex digest of a canonical `(AOI + criteria set + weights)` serialization. Identical requests hash identically and can be served from cache. |
| `aoi` | The AOI this surface was computed for. |
| `criteria_set` | Snapshot of which criteria and weights were actually used, independent of any later change to a `Criterion`'s stored weight. |
| `grid` | The common EPSG:32645 / 10m grid this raster is stored on — `origin_x/y`, `width`, `height` (see §2.2 on deterministic AOI-derived alignment). |
| `data_url` | Location of the stored raster: single-band float, values in `[0, 1]`. |
| `nodata_value` | Nodata sentinel in the *output* raster, if any (e.g. pixels outside the AOI). |
| `value_range` | Fixed `[0, 1]`. **This is a continuous normalized score, not the 1-5 display classes.** Discrete risk classes for the legend/map display are derived from this value at render time and are never what gets stored or cached here. |
| `created_at` | When this surface was computed. |

**Weighted-sum formula and normalization.** For each pixel, with
`weight_i` the AHP final weight for criterion *i* and `class_i` its
reclassified risk class (an integer 1-5, per `Criterion.reclassification_rules`):

```
R      = Σ (weight_i × class_i)         -- R ∈ [1, 5] when weights sum to 1
R_norm = (R - 1) / (5 - 1)              -- R_norm ∈ [0, 1]
```

`R_norm` is a **fixed-range linear transform**, not a min-max
normalization over the AOI's own computed values. The 1-5 bounds come
from the reclassification scheme (5 fixed classes), not from whatever
values happen to occur in a given request's output. This is deliberate:
min-max normalization would make scores incomparable across AOIs or
re-runs — a pixel scoring `R_norm = 0.8` must mean the same thing
regardless of which AOI it came from, which only holds under a fixed
reference range. Every phase that reads a risk surface (vulnerability
classification, the frontend legend, anything downstream) should use
this formula's inverse to recover `R` if it ever needs the underlying
1-5 scale back, rather than re-deriving normalization from the array.

**Nodata.** The overlay engine uses one explicit sentinel,
`RISK_SURFACE_NODATA = -9999.0` (`backend/app/overlay/compute.py`) —
chosen outside `[0, 1]` specifically so it can never be mistaken for a
real, computed score. A pixel is nodata in the output if *any*
contributing criterion is nodata at that pixel (`reclassify.RECLASSIFIED_NODATA
= 0`); it is never treated as zero-risk or silently dropped from the sum.

**Per-criterion raster snapshots.** Each criterion's own already-
reclassified raster (1-5, `RECLASSIFIED_NODATA`=0 — the same values the
weighted sum above combines, before combining) is available as its own
downloadable GeoTIFF too — `GET /api/overlay/criterion_raster/
{cache_key}/{criterion_id}.tif` — but **only after `POST /api/overlay/
report` has been generated for that `cache_key`**, by explicit design:
`POST /compute`/`/compute/stream` never write these files, so the route
404s until a report actually runs `report.py`'s
`_materialize_criterion_rasters` as a side effect. See §5's own entry
for the full reasoning (this was a deliberate scoping decision, not a
limitation worth lifting later) and `backend/app/overlay/report.py`'s
docstring for the mechanics.

### 3.5 Basin- and district-based AOI selection — `backend/app/data/basins.py`, `backend/app/basins/`, `backend/app/data/districts.py`, `backend/app/districts/`

Two **alternatives** to hand-drawing a bbox — not replacements for it or
for each other; all three (drawn bbox, selected basin, selected
district) produce the same `AOI` shape and flow through every later
stage identically.

**Basins.** Backed by HydroBASINS Asia, selectable at **level 8**
(coarser — 28,907 basins; ~547 overlap Nepal's rough extent) or **level
9** (finer sub-catchments — 77,849 basins; ~1,495 overlap Nepal's rough
extent), each loaded once from its own local shapefile
(`config.LOCAL_BASINS_PATH` / `LOCAL_BASINS_LEV09_PATH`, override via
`BASINS_SHAPEFILE_PATH` / `BASINS_LEV09_SHAPEFILE_PATH`) and cached in
memory per level. HYBAS_ID encodes region+level in its own leading
digits (verified empirically: every level-8 ID in this dataset starts
"408…", every level-9 ID "409…"), so the two levels' IDs never collide —
`GET /api/basins/{hybas_id}` still requires an explicit `level` query
param rather than relying on that encoding, since decoding a level from
an ID's digits is HydroBASINS-Asia-specific. There is no cloud fallback
for basins (unlike DEM/WorldCover/OSM) — a missing/invalid file is a
clear 503, not a degraded live-query path.

| Endpoint | Returns |
|---|---|
| `GET /api/basins?level=8\|9` | GeoJSON `FeatureCollection` of basins overlapping Nepal's *rough* extent (a generous bbox screen, not a hard restriction — cross-border basins are kept whole, never clipped) at the given level (default 8), each tagged with `hybas_id`, `level`, and `support_status`. Real-data payload at level 8 is ~3.9 MB at full geometry resolution regardless of caching (no simplification/pagination implemented — deferred, no clear need yet); response time is ~4s cold, ~0.17s once `get_basin_support_status`/`get_basin_pct_in_nepal`'s per-HYBAS_ID cache is warm (§ below). Level 9's larger feature count makes for a noticeably bigger payload than level 8's. |
| `GET /api/basins/{hybas_id}?level=8\|9` | One basin's detail: area (true polygon area, km²), `pct_in_nepal`, `support_status`, `level`, geometry. |
| `GET /api/basins/{hybas_id}/aoi?level=8\|9` | `{bbox, polygon}` — the exact shape `AOIInput` (§3.1) accepts, so a selected basin drops straight into `POST /api/overlay/compute`'s `aoi` field unchanged. |

An unsupported `level` (anything other than 8 or 9) is rejected with a
422 before any file lookup happens.

**Support status** — the fraction of a basin's own true area (EPSG:32645,
never raw degrees) that falls within Nepal's true country boundary
(`config.LOCAL_NEPAL_BOUNDARY_PATH`) when that optional file is
available, or `NEPAL_BBOX_4326` (a rough rectangular proxy) as an
automatic fallback when it isn't:

| Status | Threshold | Meaning |
|---|---|---|
| `fully_in_nepal` | ≥ 98% | The whole basin is effectively inside Nepal; edge effects are negligible. |
| `partial_likely_adequate` | ≥ 50%, < 98% | Most of the basin's hydrology is captured; DEM/WorldCover data itself is globally available so there's no raw *data* gap at the border, but a meaningful share of the catchment lies outside the usual analysis frame. |
| `likely_degraded_at_edges` | < 50% | Most of the basin is outside Nepal; treat results with low confidence. |

These thresholds are a judgment call, not derived from an external
standard — see the basins-phase decisions-to-confirm record for the
reasoning. Real-data breakdown across the ~547 level-8 basins overlapping
Nepal's rough extent: 155 `fully_in_nepal`, 41 `partial_likely_adequate`,
351 `likely_degraded_at_edges` — expected for a rectangular screening
filter against a mountainous country's actual (much smaller, irregular)
territory.

**Nepal's true boundary source**: OCHA/HDX's "Nepal - Subnational
Administrative Boundaries" COD-AB dataset
(https://data.humdata.org/dataset/cod-ab-npl), produced by Nepal's own
Survey Department + UN Resident Coordinator's Office, quality-assured by
ITOS/USAID — licensed **CC BY-IGO** (attribution required, but
**commercial use and redistribution are both permitted**), superseding
this project's earlier HERMES source (non-commercial use only, no
redistribution without consent) and evaluated against GADM (same
non-commercial-only restriction as HERMES, so not actually a fix) before
settling on HDX. Still kept out of version control like every other raw
source under `backend/data/raw/` (that directory's own `.gitignore`
rules) — this project's general local-data convention, not a
license-driven exception the way HERMES was.

The same file's admin-level-2 layer also backs district-based AOI
selection, below.

**Classification caching**: `classify_support_status`/`pct_area_in_nepal`
are recomputed on a cache miss and cached per HYBAS_ID
(`get_basin_support_status`/`get_basin_pct_in_nepal`, backed by
module-level dicts in `basins.py`) — a basin's geometry never changes at
runtime, so this is a pure speedup with no behavior change. Measured on
the real dataset: ~4.0s cold (547 basins classified against Nepal's full
boundary polygon) vs. ~0.17s once warm. Invalidated automatically by
`reset_basins_cache()`/`reset_nepal_boundary_cache()`, since the
classification is a function of both the basin's own geometry and
whichever Nepal reference geometry is currently loaded.

**Districts.** Backed by the same HDX COD-AB dataset's admin-level-2
layer — Nepal's 77 districts (`config.LOCAL_ADMIN_DISTRICTS_PATH`,
override via `ADMIN_DISTRICTS_SHAPEFILE_PATH`), loaded once and cached in
memory, mirroring `basins.py`'s own shape (`app/data/districts.py`,
`app/districts/`). Unlike a basin, a district is by definition entirely
within Nepal, so there is no `support_status` concept here.

| Endpoint | Returns |
|---|---|
| `GET /api/districts` | GeoJSON `FeatureCollection` of all 77 districts, each tagged with `pcode` (e.g. `"NP0101"`), `name`, and `province` (the parent admin-1 name). |
| `GET /api/districts/{pcode}` | One district's detail: `pcode`, `name`, `province`, area (true polygon area, km²), geometry. |
| `GET /api/districts/{pcode}/aoi` | `{bbox, polygon}` — the exact shape `AOIInput` (§3.1) accepts, so a selected district drops straight into `POST /api/overlay/compute`'s `aoi` field unchanged, exactly like a selected basin. |

Since a district selection carries a true `polygon` the same way a basin
selection does, it automatically gets every existing polygon-aware
behavior with zero district-specific code needed anywhere downstream of
`district_to_aoi`: exemption from the bbox area cap (`app/common/aoi.py`),
true-shape masking of the computed risk surface
(`mask_risk_surface_to_polygon`), and basin-vs-bbox true-shape clipping
in `twi`/`drainage_density`/`hand`'s flow-accumulation pipeline
(§3.6) — that clipping logic checks `AOI.polygon is not None`, not
"is this specifically a basin."

### 3.6 Criterion sources & the pluggable registry — `backend/app/overlay/sources.py`

A `Criterion.source` (§3.2) is resolved to its raw physical layer through
a small, explicit, **pluggable** registry — `register_source(name, fn)`
maps a source name to a `(AOI) -> (raw_array, grid, nodata, attribution,
warning)` function (`warning` is `str | None`, `None` for most sources;
non-`None` for `twi`/`drainage_density`/`hand` (AOI-edge flow-routing
reliability), `rainfall` (elevation-blind IDW interpolation), and
`flood_hazard_meteor` (below the modeled-domain coverage threshold) —
see each source's own module for its exact condition);
`resolve_criterion_raster`
looks a criterion's declared `source` up in it, then applies
`reclassification_rules` (§2.3, §3.2). Adding a new source needs only a
matching function + one `register_source()` call — see `sources.py`'s
own module docstring for the exact steps, and
`tests/overlay/test_sources.py`'s registry-extensibility test, which
proves this end-to-end by registering a throwaway dummy source from the
test file itself, through the public `register_source()` function only,
with zero changes to `sources.py` or any other `overlay/` file.

| `source` | Raw layer | Continuous/categorical | Backing module |
|---|---|---|---|
| `dem_elevation` | Elevation (m) | Continuous | `app/data/dem.py` |
| `dem_slope` | Slope (degrees, Horn's method) | Continuous | `app/data/dem.py` |
| `worldcover_land_cover` | ESA WorldCover class code | Categorical | `app/data/worldcover.py` |
| `dist_to_river` | Euclidean distance to nearest river/stream/canal (m) | Continuous | `app/data/distance_raster.py` (+ `app/data/osm.py`'s `get_waterways`) |
| `dist_to_road` | Euclidean distance to nearest road (m) | Continuous | `app/data/distance_raster.py` (reuses `get_osm_features(aoi).roads` — no separate OSM query) |
| `twi` | Topographic Wetness Index | Continuous | `app/data/hydrology.py` |
| `drainage_density` | Local drainage density (km stream / km² window) | Continuous | `app/data/hydrology.py` |
| `building_density` | Local building-footprint coverage fraction (0-1) | Continuous | `app/data/density_raster.py` (reuses `get_osm_features(aoi).buildings` — no separate OSM query) |
| `population_density` | Meta/CIESIN HRSL population density (people/km²) | Continuous | `app/data/population.py` |
| `hand` | Height Above Nearest Drainage (m) — elevation above the nearest stream cell along the D8 flow path | Continuous | `app/data/hydrology.py` |
| `soil_infiltration` | ISRIC SoilGrids topsoil (0-5cm) sand content (%), used as an infiltration-capacity proxy | Continuous | `app/data/soil.py` |
| `rainfall` | Precipitation ETCCDI index (default Rx1day, configurable), interpolated (IDW) from Nepal's DHM rain-gauge network | Continuous | `app/data/rainfall.py` |
| `precipitation_chirps` | CHIRPS-2.0 satellite precipitation, 1981-2024 mean-annual climatology | Continuous | `app/data/chirps.py` |
| `flood_hazard_meteor` | METEOR Project modeled flood water depth (m), Fathom global flood hazard framework, default Fluvial Defended 1-in-100y | Continuous | `app/data/meteor_flood.py` |

**Distance rasters** (`distance_raster.py`): a generic
`compute_distance_raster(features, grid)` rasterizes arbitrary vector
features onto the common grid and runs a Euclidean distance transform
(`scipy.ndimage.distance_transform_edt`), quantized to the grid's own
10m resolution (accurate to within about one pixel diagonal of the true
vector distance — the same precision every other raster in this layer
already operates at). Not river/road-specific, so a future "distance
from X" criterion can reuse it directly.

**Density rasters** (`density_raster.py`): a generic
`compute_density_raster(features, grid, window_radius_m)` rasterizes
arbitrary polygon (or line/point) features onto the common grid
(`all_touched=False` — deliberately different from
`compute_distance_raster`'s `all_touched=True`: correct for area
coverage, where counting a pixel a polygon edge merely clips would
overstate density), then runs a circular moving-window mean of that
mask — the same "Line Density"-style construction `hydrology.py`'s
drainage density already uses, generalized from line length to area
coverage. `building_density` is its first, and Exposure cluster's first
criterion (what's at risk, rather than the hazard's own physical
behavior — every other criterion here describes that instead): local
building-footprint coverage (0-1) within
`config.BUILDING_DENSITY_WINDOW_RADIUS_M` (default 200m — smaller than
`DRAINAGE_DENSITY_WINDOW_RADIUS_M`'s 500m, since buildings vary at a
finer spatial scale than stream networks), reusing
`get_osm_features(aoi).buildings` — no new OSM query, same "no separate
query" principle `dist_to_road` already follows for roads. `nodata` is
always `None` — density is defined everywhere (0 where no buildings
fall within the window, never "unknown"; `get_osm_features` itself is
what raises if the underlying source is unavailable at all) — the first
source in this registry to actually use `reclassify.py`'s "`nodata is
None`, so every pixel is valid" code path rather than a real sentinel.

**Local OSM extract discovery** (`osm.py`): `config.LOCAL_OSM_DIR` is a
*directory*, not one fixed filename — `_find_local_pbf()` globs it for
the most-recently-modified `*.osm.pbf`, the same "glob a directory"
pattern `local_source.py` already uses for DEM/WorldCover. This was a
real bug fix, not a preemptive design choice: the original single fixed
name (`nepal-latest.osm.pbf`) never matches a real downloaded extract,
whose filename always carries its own extract date (e.g.
`nepal-260821.osm.pbf`) — caught when a real 412MB Nepal extract was
placed for verification and silently fell through to the (unconfigured)
R2 fallback instead of ever being used. Parsing a real full-country
extract is genuinely expensive: verified live, pyrosm's first
extraction on a freshly-opened `OSM(...)` object took ~145-210s (a
one-time low-level parse of the whole file); a *second* extraction on
that same already-parsed object took 0.02s. `_load_local_osm`
(`@lru_cache(maxsize=4)`, keyed by `(path, bbox)`) exists so
`get_osm_features` (buildings+roads) and `get_waterways`, when both
needed for the same AOI in the same request — a normal case, since this
project's frontend lets a user check both `dist_to_road` and
`dist_to_river` at once — share that one parse instead of each paying it
separately; verified live (0.01s for the second call once the first had
run). Still ~145-210s for whichever call runs first against a real AOI
with no local file previously seen — `POST /api/overlay/compute`'s own
response time inherits that on a cache miss, which is well beyond what
"a few seconds" implies; the frontend's compute-in-progress message
says so explicitly when a road/river-distance criterion is selected.

**Hydrology** (`hydrology.py`): `twi`, `drainage_density`, and `hand` all
build on a shared DEM sink-fill + D8 flow-direction + flow-accumulation
pipeline (`compute_flow_accumulation`), using **pysheds** (not
richdem — richdem's only PyPI wheels are Linux/macOS-only, which would
break local testing on a plain Windows environment outside Docker, as
this project's is; pysheds ships a pure-Python/NumPy wheel with
equivalent algorithms, verified to produce hand-checked correct results
on both Windows and in the Docker image). pysheds pulls in `numba` as a
hard dependency; `requirements.txt` pins `numba>=0.61` explicitly since
the version pip resolves by default (0.60.0) does not support this
project's pinned `numpy==2.1.2`.

- When the AOI carries a true `polygon` (a basin-derived AOI, §3.5), the
  DEM is clipped to that polygon *before* flow routing — every pixel
  outside it becomes nodata, so flow accumulation has no way to route
  across the basin boundary from ground that isn't really part of that
  basin. This is what makes the basin case hydrologically correct,
  since a basin has no external inflow by definition.
- When the AOI is a plain bbox (`polygon` is `None`), the full
  rectangular grid is used as-is, and the result's `warning` field
  (`hydrology.EDGE_RELIABILITY_WARNING`) flags that flow-accumulation-
  derived values near the AOI's own edges may be underestimated — a
  known limitation (the same kind of edge effect `dem.py`'s Horn's-
  method slope already has). This is a dedicated field, never folded
  into `attribution` (which always stays the plain, unmodified source
  citation) — see "Response fields" below.
- Cached per-AOI like every other source, but `version`-keyed
  (`_hydrology_cache_version`) so a basin-derived AOI and a plain bbox
  AOI that happen to share the same `bbox_4326` never share a cache
  entry — `AOI.cache_key()` itself is deliberately bbox-only (§3.1's
  `polygon` row), so this is exactly the "future consumer that needs
  true-shape correctness" case that decision anticipated.

`twi`: `TWI = ln(α / tan(β))`, `α` (specific catchment area) =
flow-accumulation cell count × `resolution_m` (the standard Moore et al.
(1991) convention — upslope contributing area divided by contour length,
approximated on a D8 grid as one cell width per contributing cell — so
TWI values here are directly comparable to published-literature
thresholds, rather than offset by a constant `ln(cell_size)` from them),
`β` = local slope in radians (reusing `dem.compute_slope_degrees` —
Horn's method — on the AOI's own unfilled elevation, not the sink-filled
DEM used for flow routing). `tan(β)` is floored to
`tan(MIN_SLOPE_RADIANS)` on flat ground so TWI never diverges to
+infinity.

**Response fields.** `POST /api/overlay/compute`'s response carries two
separate, never-conflated per-source fields: `attribution` (deduplicated
citation strings, unchanged by this phase) and `source_warnings` (a list
of `{criterion_id, message}`, one entry per criterion whose registered
source function returned a non-`None` warning — empty when nothing has
anything to flag). Only `twi`/`drainage_density`/`hand` on a plain bbox
AOI ever populate it today, but the field itself is generic — any future
source can use it the same way, with no special-casing anywhere in the
overlay engine beyond the registry's own 5-tuple contract.

`drainage_density`: flow accumulation is thresholded
(`config.DRAINAGE_DENSITY_THRESHOLD_CELLS`, not literature-calibrated
yet — a placeholder pending calibration against a real Kathmandu Valley
stream network) to extract a synthetic stream network, then turned into
a continuous per-pixel raster via a circular moving-window line-density
transform (`config.DRAINAGE_DENSITY_WINDOW_RADIUS_M`) — the same
construction as ArcGIS Spatial Analyst's "Line Density" tool — rather
than a single catchment-wide scalar, so it can serve as a pixel-weighted
AHP criterion like every other source here. Both parameters are
env-overridable and folded into the cache version, so recalibrating
either one never needs a code change or silently reuses a stale result.

**Per-request threshold override**: `config.DRAINAGE_DENSITY_THRESHOLD_
CELLS`'s deployment-wide default can be overridden per request via
`OverlayCriterionInput.stream_threshold_cells` (`POST /compute`,
`/compute/stream`, `/report`) and `CriterionBreaksRequest.
stream_threshold_cells` (`POST /criteria/breaks`) — a genuine
scientific-parameter knob (see the frontend's own shared "Stream network
threshold" control, below), not a config change. Threaded through
`overlay/sources.py`'s registry as a keyword arg every adapter accepts
(and all but `drainage_density`/`hand` ignore, via `**_kwargs`) rather
than special-cased in the generic dispatch, exactly the "adapters absorb
source-specific complexity, the registry never does" property this
module's own docstring already establishes for per-AOI data — now
extended to per-request parameters too. `get_drainage_density`/`get_hand`
(hydrology.py) both gained an optional `threshold_cells` parameter,
`None` meaning "use the config default" (every call site before this
existed). **A real cache-key bug of the exact same class already fixed
once for `reclassification_rules`** was caught and fixed while wiring
this up: `overlay/compute.py`'s `compute_cache_key` only picked 3 known
keys out of each criterion's dict, so a request with an overridden
threshold and one without would have hashed identically and silently
served each other's cached raster — `stream_threshold_cells` is now a
4th key in that same normalization, covered by a dedicated regression
test (`test_cache_key_changes_when_stream_threshold_cells_changes`).

`hand` (Height Above Nearest Drainage): for each pixel, the elevation
difference to the nearest stream cell along its D8 flow path (not
straight-line nearest) — computed via **pysheds' own `compute_hand`**
(chosen over a hand-rolled flow-path descent because it reuses the exact
`_DIRMAP`/Raster/ViewFinder conventions `_run_pysheds_pipeline` already
established, with no second D8 implementation introduced), fed the same
conditioned (sink-filled) DEM flow direction was itself derived from —
deliberately *not* the unfilled elevation `twi`'s slope term uses, since
a flow network derived from the filled DEM needs a height measurement
consistent with that same filled surface. Shares `drainage_density`'s
`config.DRAINAGE_DENSITY_THRESHOLD_CELLS` stream-network threshold (the
same synthetic stream network both are measured against, not a second
one) and is folded into the same cache-version string, so recalibrating
that one threshold correctly invalidates both. Low HAND means a pixel
sits near its local drainage's own elevation — high flood susceptibility
— handled entirely at the reclassification-rules level
(`frontend/src/config/criteria.js`'s `hand` entry sets
`riskDirection: 'descending'`, the same convention `dem_elevation`/
`dist_to_river` already use), never inverted inside this module itself.

A real finding from hand-verifying this against actual pysheds output
(not assumed, and not previously documented anywhere in this codebase):
**pysheds' `compute_hand` cannot resolve the outer 1-pixel ring of any
finite grid** — a border cell never has a full D8 neighborhood to trace
a path through, regardless of how close it is to a stream, so it always
comes back unresolved (confirmed on synthetic grids from 5×5 to 11×11).
This is a *stricter* edge effect than flow accumulation's own "may be
underestimated near the edges" (`EDGE_RELIABILITY_WARNING`) — `hand`'s
edge pixels aren't underestimated, they're nodata outright — but per an
explicit decision to reuse the existing warning rather than add a second
channel, a plain bbox AOI's `hand` result still surfaces that same
warning text/field, not a HAND-specific one. Verified live end to end
against the real running backend over a real ~30 km² Kathmandu AOI:
90% valid-pixel coverage, values in the expected `[0, 1]` normalized
range after reclassification.

**A second, larger real-world finding**, surfaced when a user reported a
visible branching gap pattern in a rendered `hand` risk surface over the
full Kathmandu Valley (~1518×1550 pixels) and investigated live rather
than guessed at: **an internal pit `fill_pits`/`fill_depressions`/
`resolve_flats` didn't fully resolve — not only the outer edge — breaks
HAND for its *entire upstream contributing area*, not just the pit cell
itself.** This is a different mechanism from the edge-ring finding above
(which is a purely geometric effect present even on a toy DEM with zero
real depressions): flow accumulation only needs a cell's own upstream
sum, unaffected by what happens further downstream, but HAND needs the
*full* downstream trace to reach a real stream cell to succeed — a
single unresolved pit anywhere along that trace poisons every cell
upstream of it. Measured live on that real AOI: 209,211 of ~2.35M
pixels (~12%) came back nodata despite being otherwise valid in
`flow.valid_mask` (~3% base-invalid from pits/edges alone) — confirmed
by sampling 15 such cells and manually tracing their D8 path
step-by-step: every one terminated at an unresolved intermediate cell,
never at the grid edge (1–38 steps each). Reproduced deterministically
in `tests/data/test_hydrology.py`'s
`test_internal_unresolved_pit_propagates_nodata_upstream` with a
hand-crafted flow-direction grid (no need to reproduce an actual
unresolvable real DEM). **Decision, confirmed**: documented as a known
limitation rather than fixed — a fix would mean either improving DEM
conditioning (risking a change to `twi`/`drainage_density`'s own
results too, which reuse the same conditioned DEM) or redefining what
counts as a valid "nearest drainage" reference (e.g. falling back to
the nearest unresolved pit as a degenerate local drainage point) — both
real scientific-methodology choices, not bug fixes, left for a future
phase if `hand`'s practical gap rate turns out to matter for real use.

`soil_infiltration` (`app/data/soil.py`): topsoil (0-5cm) sand content
(%) from **ISRIC SoilGrids 2.0**, local-check-first with a live cloud
fallback against ISRIC's own public, unauthenticated hosting
(`files.isric.org`) — same shape as `dem.py`/`worldcover.py`/
`population.py`. Chosen over HYSOGs250m (the other live-fetchable
soil-infiltration dataset investigated): a real CMR (Common Metadata
Repository) granules-API check during evaluation confirmed HYSOGs250m's
actual granule URLs (both HTTPS and S3) sit under NASA Earthdata's
`/protected/` path, requiring Earthdata Login, while a live probe against
SoilGrids' real VRT succeeded with zero credentials.

Sand, not a derived USDA Hydrologic Soil Group, is what's used here:
sandier (coarser) soil drains faster and infiltrates more, so higher
sand content means lower flood risk (`frontend/src/config/criteria.js`'s
`soil_infiltration` entry sets `riskDirection: 'descending'`) — the same
directional reasoning a full Hydrologic Soil Group classification is
ultimately built on, without that classification's extra machinery
(needing clay content too, plus a USDA texture-triangle lookup).
Flagged as a decision to confirm.

**Two real, live-verified findings specific to this source, neither
true of any other source in this registry:**

- **Source CRS is not EPSG:4326.** Verified live during implementation:
  `rasterio.open()` against the real `sand_0-5cm_mean.vrt` reports
  Interrupted Goode Homolosine, a global projection in meters — unlike
  every other cloud source here (DEM/WorldCover/Population), whose
  windowed reads pass `aoi.bbox_4326` straight in as read-window bounds
  because their sources' own transforms are already in that same
  coordinate space. `soil.py`'s `_soilgrids_window_bounds` explicitly
  reprojects the AOI bbox into the source's own CRS
  (`rasterio.warp.transform_bounds`) before building the window;
  skipping this would silently read the wrong patch of the globe rather
  than raise an error (Homolosine coordinates numerically resemble
  large UTM-like meter values). `grid.py`'s `reproject_to_grid` itself
  needed no change — it already delegates to `rasterio.warp.reproject`,
  which supports arbitrary source CRS via GDAL/PROJ regardless of what
  that CRS is. Confirmed live that Nepal sits comfortably inside a
  single uninterrupted Homolosine lobe (the projection's interruptions
  are placed in oceans specifically to avoid cutting through populated
  landmasses): a real window read over Kathmandu Valley came back
  spatially coherent, not the scrambled values a seam-crossing read
  would produce.
- **A real per-pixel value-scaling factor, confirmed rather than
  assumed.** SoilGrids' raw int16 raster value is not a percentage —
  ISRIC's own published SoilGrids conversion-factor table gives sand's
  mapped unit as g/kg, conversion factor 10, conventional unit g/100g
  (%). `soil.py` divides by 10 before reprojection (`_scale_and_mask`),
  so every value downstream of this module — reclassification
  breakpoints, the criterion's displayed `%` unit — is already in the
  conventional percentage, not SoilGrids' internal encoding. Source
  nodata (`-32768`, verified live) is converted to `NaN` in that same
  step *before* scaling, specifically to avoid a real class of bug the
  test suite (`test_scale_and_mask_turns_source_nodata_into_nan_not_a_
  scaled_sentinel`) exists to catch: dividing the raw `-32768` sentinel
  by 10 first would silently produce a plausible-looking but wrong
  `-3276.8%` instead of being recognized as nodata.

**A known limitation, found live rather than assumed correct:** a tiny
AOI (this project's own ~0.6km test fixture bbox, centered on Kathmandu
Durbar Square) reads back as a 3×4-pixel window at SoilGrids' native
250m resolution with **all 12 pixels genuinely nodata** — a real,
small-scale gap in SoilGrids' own coverage at that exact spot, not a
bug in this module (a wider window across the same valley, tried during
the same live check, came back ~74% valid). Per this project's
established `compute_risk_surface` rule (any nodata input pixel poisons
that pixel's combined result), a user who draws a very small AOI that
happens to fall in one of these gaps and selects `soil_infiltration`
could see the risk surface come back fully nodata for that request —
the same class of outcome `hand`'s edge/pit gaps above already document,
not previously seen for any other source in this registry (none of
which has SoilGrids' comparatively coarse 250m native resolution).
Documented as a known limitation rather than mitigated (e.g. via a
buffered read or a coarser fallback), matching the same "document
first, decide on a fix only if it matters in practice" approach already
taken for `hand`'s gaps. Flagged as a decision to confirm.

### 3.7 Shelter-site identification — `backend/app/overlay/shelters.py`

`POST /api/overlay/shelters` ranks real OSM building footprints inside
an AOI as candidate emergency-shelter **sites**, given the same
`aoi`/`criteria`/`final_weights`/`complete` inputs `POST /compute`
already takes (plus the optional knobs below) — reusing
`compute_overlay`'s own risk-surface cache exactly the way
`POST /report` already does, so a caller that already computed this
combination pays no extra risk-surface cost.

**Scope, explicit.** This identifies suitable sites from the AOI's
*existing building stock*, never existing tagged emergency shelters or
shelter-type buildings (schools, hospitals, community halls) specifically
— this project's buildings dataset (§3.6's `app/data/osm.py`) is
geometry-only, with no amenity/`building=school|hospital` tag preserved
through the FlatGeobuf extract pipeline. A real building's own footprint
area (computed on the UTM grid, §2.1's CRS convention) is used as a size
proxy instead: any building at or above `min_footprint_area_m2` (default
`config.SHELTER_MIN_FOOTPRINT_AREA_M2`, 250 m² — a structurally
reasonable, not-literature-calibrated placeholder, in the same
documented-placeholder spirit as `DRAINAGE_DENSITY_THRESHOLD_CELLS`) is
treated as a candidate large/institutional-scale structure. This is a
site-suitability ranking from what's really on the ground, not a
classification of what a building actually *is*.

**Scoring.** Every candidate is scored on three factors:

| Factor | Signal | Direction |
|---|---|---|
| Safety | The building's own hazard class (1-5), majority-overlap sampled — the exact same rule/implementation `building_classification.py`'s report-facing `classify_buildings` already uses, reused rather than reimplemented so the two features can never disagree about a building's hazard class. | Any candidate in `HIGH_RISK_CLASSES` (4-5) is **excluded outright**, never merely down-ranked — a site itself in the high/very-high hazard zone cannot be a safe shelter regardless of how it scores otherwise. |
| Accessibility | Distance to the nearest road, `distance_raster.py`'s existing `dist_to_road` machinery. | Closer is better. |
| Service value | Local population density at the site, `population.py`. | Higher is better. |

Each factor is **min-max normalized across the AOI's own surviving
candidates** — deliberately *not* `RiskSurface.value_range`'s fixed
`[1, 5]`-derived `[0, 1]` scale (§3.4). That fixed-range convention
exists to keep one *stored, cross-AOI-comparable hazard score* meaning
the same thing everywhere; a shelter ranking is inherently a
within-AOI comparison ("which of THESE buildings, in THIS area, is the
better choice") with no cross-AOI comparability claim to protect, so
ordinary min-max normalization is the right tool here, not a violation
of that convention. A candidate missing a signal at its own location
(e.g. a population coverage gap) scores at the midpoint (0.5) on that
factor — neither penalized nor favored for a data gap. The three
normalized scores combine via a transparent weighted mean
(`safety_weight`/`accessibility_weight`/`service_weight`, equal thirds
by default, all caller-overridable) into one `suitability_score` (0-1,
AOI-local only), and candidates are ranked descending, truncated to
`top_n` (default `config.SHELTER_DEFAULT_TOP_N`, 20).

**Response.** Each returned candidate carries its footprint geometry
(the buildings source's own original CRS, EPSG:4326 in production),
footprint area, hazard class/label, distance to road (nullable — null
only if the AOI has zero road features at all), population density
(nullable), `suitability_score`, and `rank`. The response also reports
`total_buildings_in_aoi` and three exclusion counts
(`excluded_too_small`/`excluded_high_hazard`/`excluded_no_data`) so a
caller can tell "zero candidates" apart from "every building was
excluded, and here's why."

## 4. Local development

Everything runs locally via Docker Compose, bound to `127.0.0.1` only —
nothing is exposed beyond localhost.

```
docker compose up
```

| Service | URL | Notes |
|---|---|---|
| `frontend` | http://localhost:5173 | Vite dev server, React + MapLibre GL |
| `backend` | http://localhost:8000 | FastAPI, hot-reload via mounted volume |
| `db` | localhost:5432 | PostGIS (`postgis/postgis:16-3.4`) |

`backend/data/` (both `raw/` — DEM/WorldCover/OSM/basins local files — and
the per-AOI processed `cache/`) is volume-mounted into the backend
container at `/app/data`, matching `config.py`'s own default `DATA_DIR`
resolution inside it. Without this mount every local-check-first source
falls straight to its cloud/R2 fallback (or, for basins/OSM with no R2
configured, a 503) regardless of what's actually placed on the host —
this was a real bug (not caught until basin selection and OSM-backed
criteria were actually exercised through `docker compose up` rather
than a directly-run backend process), fixed by adding the mount.

Backend and frontend source directories are volume-mounted into their
containers so edits on the host are picked up without rebuilding the image.
See `.env.example` for the (dev-only, non-secret) default Postgres
credentials — copy it to `.env` before first run if you want to override
them.

## 5. Status

- `/schemas` contracts, this SPEC, and the Docker Compose skeleton: done.
- Backend: `GET /` and `GET /health` (skeleton), plus a working **AHP
  engine** (`backend/app/ahp/`) exposing `POST /api/ahp/compute` — exact
  eigenvector priority weights (primary) and the column-sum-and-average
  approximation (diagnostic only), consistency checking (CR < 0.10, per
  §3.3), and two-level cluster/criteria weight composition. Covered by
  `backend/tests/`, including test cases verified against published
  literature matrices (see the citations in `backend/app/ahp/core.py`).
- Backend: a **geospatial data layer** (`backend/app/data/`) for the 3
  input sources — Copernicus GLO-30 DEM (+ derived slope), ESA WorldCover
  10m, and OSM buildings/roads. Every source follows local-check-first /
  cloud-fetch-fallback: an optional pre-downloaded file under
  `backend/data/raw/` is used if present and it covers the AOI; otherwise
  DEM and WorldCover fall back to a live windowed read from their public,
  anonymous-access S3 COG buckets, and OSM falls back to a pre-processed
  extract on a configurable bucket (Cloudflare R2 in production) — never
  the live Overpass API. Every source reprojects/resamples onto the
  common per-AOI grid (§2.2), assigns an explicit output nodata value,
  and is cached per-AOI (`backend/data/cache/processed/`, separate from
  the raw sources) so repeat requests never re-fetch or re-reproject.
  Reclassification (continuous/categorical values -> 5 risk classes) is
  a generic engine driven entirely by a criterion's
  `reclassification_rules` (schemas/criterion.schema.json), not
  hardcoded per criterion. Covered by `backend/tests/data/`, including 2
  real-network integration tests (marked `slow`, verified against live
  Copernicus/WorldCover data during implementation) and R2/local-file
  fallback behavior confirmed via mocking.
- Backend: an **overlay engine** (`backend/app/overlay/`) exposing
  `POST /api/overlay/compute` — combines Phase 1's AHP `final_weights`
  and Phase 2's reclassified criterion rasters into the composite
  `RiskSurface` described in §3.4 (fixed-range normalization,
  `RISK_SURFACE_NODATA`). Rejects an incomplete AHP weight set
  (`complete=False`) rather than computing on non-normalized weights, and
  never re-reprojects — a grid mismatch between two criteria is a hard
  error, not something this module works around. Cached per
  `RiskSurface.cache_key` (AOI + criteria set + weights — distinct from
  Phase 2's per-source AOI cache, since the same AOI yields a different
  surface under different weights) and materialized as a GeoTIFF for the
  response's `data_url` — served back over HTTP by
  `GET /api/overlay/risk_surface/{cache_key}.tif` (`data_url` is that
  route's path, not a raw filesystem path), so the frontend can load a
  computed surface directly as a raster/image source. Every AOI-accepting
  request (this endpoint today) goes through the shared `AOIInput` model
  (§3.1), so an oversized AOI is rejected with a 422 before any Phase 2
  fetch happens. Covered by `backend/tests/overlay/`, including an
  end-to-end integration test using the real AHP engine and real Phase 2
  local-fixture data together with no mocking.
- Backend: **basin-based AOI selection** (§3.5) — `backend/app/data/basins.py`
  (HydroBASINS lookup/classification/`basin_to_aoi`) and
  `backend/app/basins/` (`GET /api/basins`, `/{hybas_id}`,
  `/{hybas_id}/aoi`). `AOI` (`backend/app/data/aoi.py`) now optionally
  carries a true `polygon` alongside `bbox_4326` — additive only; every
  existing bbox-only AOI consumer (DEM/WorldCover fetch, reclassification,
  the overlay engine) is unmodified and unaffected, verified by the full
  Phase 1-3 test suite passing with zero changes. The correct dataset
  (HydroBASINS Asia, level 08, "Standard" polygon format — 28,907
  basins) and Nepal's true country boundary (used for accurate
  support-status classification, falling back to a rough bbox proxy when
  absent) are both now in place and verified end to end against the real
  files; earlier in this phase the file initially placed was HydroBASINS'
  "Pour Points" product (point geometry, wrong dataset entirely) —
  `basins.py` still validates for exactly that mismatch and fails with a
  clear, actionable error rather than misbehaving on point geometry,
  should it recur. Per-HYBAS_ID classification caching brings real-data
  `GET /api/basins` from ~4.0s cold to ~0.17s warm (§3.5). All automated
  tests still use a small synthetic fixture
  (`tests/data/fixtures/basins/`), never the real ~100MB+ downloads.
- Backend: **4 new criterion sources** (§3.6) — `dist_to_river`,
  `dist_to_road` (`backend/app/data/distance_raster.py`, plus
  `osm.py`'s new `get_waterways()`), and `twi`, `drainage_density`
  (`backend/app/data/hydrology.py`, DEM sink-fill + D8 flow routing via
  pysheds) — registered through `overlay/sources.py`'s now-pluggable
  `register_source()` mechanism alongside the original 3 Phase 2
  sources. Basin true-shape clipping (`AOI.polygon`, previously unused
  by anything) is now actually exercised: `twi`/`drainage_density` clip
  flow accumulation to a basin's true boundary when available, falling
  back to the AOI's bbox (with an explicit edge-reliability note in the
  response) otherwise. Covered by `backend/tests/data/test_hydrology.py`
  (a hand-verified synthetic V-shaped-valley DEM confirming flow
  actually converges toward the valley bottom, and that polygon-clipped
  vs. bbox-unclipped runs produce different, exercised results near the
  clip boundary), `test_distance_raster.py`, `test_osm.py`'s new
  waterways tests, and `test_sources.py`'s registry-extensibility test.
  Full Phase 1-4 suite passes unmodified alongside these additions.
- Frontend: a working **React + MapLibre GL map UI** (`frontend/src/`),
  replacing the earlier blank skeleton — draw-a-bbox or select-a-basin
  AOI selection, criteria checkboxes grouped by cluster, three weighting
  modes (equal — default, computed client-side, no AHP call at all;
  full AHP pairwise comparison, live-computed via `POST /api/ahp/compute`;
  or direct numeric entry, auto-normalized to sum to 1), `POST /api/
  overlay/compute` + the resulting GeoTIFF rendered as a colorized raster
  overlay (client-side `geotiff` decode + `proj4` UTM→WGS84 corner
  reprojection), a reclassification breakdown and attribution/warnings
  display, and a placeholder-values warning banner (§3.2's default
  `reclassification_rules` are equal-interval placeholders, not
  literature-sourced — see the per-criterion config in
  `frontend/src/config/criteria.js` for the exact values, and note
  below on cluster assignment). All 3 backend engines exercised together
  end-to-end via headless-browser testing during implementation, not just
  built against the API contract in isolation.
  - AHP mode deliberately does **not** require every one of the 5
    canonical clusters to have a selected criterion (unlike the
    backend's own `AHPComputeResponse.complete`, which does) — it only
    requires every cluster that has a *selected* criterion to have a
    consistent (CR < 0.10) within-cluster comparison, then renormalizes
    the backend's `final_weights` over just the selected criteria. This
    mirrors equal-weights mode's own philosophy (never requires touching
    every cluster), and was originally what made AHP mode usable at all
    before `building_density` existed (Exposure had no criterion at
    all); kept even now that it does, since there's no reason to force
    every one of the 5 clusters into every analysis.
  - Criterion → cluster assignment (`frontend/src/config/criteria.js`):
    Topographic = elevation, slope, TWI; Hydrological = distance-to-
    river, drainage density; Land Use = land cover; Infrastructure =
    distance-to-road; Exposure = building density (§3.6).
- Frontend: **night mode** (a toggle in the sidebar header, persisted to
  `localStorage`, defaulting to the OS's own `prefers-color-scheme`) —
  every CSS color is a custom property redefined once under
  `:root[data-theme='dark']` (`frontend/src/index.css`), and the map's
  own basemap swaps live between OSM's standard tiles and CARTO's free
  "Dark Matter" tiles (`basemaps.cartocdn.com` — OSM has no official
  dark style of its own; CARTO's is free, no key/signup, rendered from
  OSM data too) via MapLibre's `setTiles()`, no full style/map reload.
  Both tile providers' attribution is shown together regardless of which
  is active, rather than wiring a second dynamic attribution control.
  The sidebar is also now 420px (was 340px).
- Backend + frontend: **user-defined reclassification breaks**
  (`POST /api/overlay/criteria/breaks`, `app/overlay/breaks.py`) — for
  any continuous criterion, computes equal-interval, quantile, and
  Fisher-Jenks natural-breaks candidate break points (4 interior breaks
  each, 5 classes fixed by schemas/criterion.schema.json's risk_class
  range) from that criterion's *actual* raw value distribution over the
  requested AOI, resolved through the exact same registry
  (`overlay/sources.py`) the overlay engine itself uses — a 9th/10th/...
  criterion source gets this for free too. Jenks (`jenkspy`, a small
  C-accelerated implementation, not hand-rolled) is capped to a
  deterministic (fixed-seed) sample of `JENKS_SAMPLE_SIZE` (10,000)
  valid pixels for responsiveness on a large AOI — the same practice
  QGIS's own Jenks classifier uses; equal-interval/quantile use the full
  population, no sampling needed. The frontend's per-criterion
  classification editor (`ClassificationEditor.jsx`, expandable under
  each checked criterion in the Criteria panel) lets the breaks be
  auto-filled from any of the 3 methods and then still hand-edited
  (`ComputePanel.jsx` blocks compute with a clear message if they end up
  out of order), or edited directly as "Manual" from the start;
  categorical `worldcover_land_cover` instead gets a simple per-legend-
  code risk-class editor (no "breaks" concept applies to discrete
  codes). Verified live: Jenks and quantile breaks for the same real AOI
  come back genuinely different, data-driven values (e.g. elevation
  breaks in the 1299-1327m range for one tested AOI, nothing like the
  static 1360/1520/1680/1840m defaults) — not a coincidental match to
  the static defaults, confirming the fetch and the resulting
  reclassification_rules are actually AOI-specific.
- Backend: fixed a real bug in `app/data/osm.py`'s local-file discovery
  (config now takes a directory, `LOCAL_OSM_DIR`, globbed for the most
  recently modified `*.osm.pbf`, rather than one fixed filename that a
  real downloaded extract's own dated filename would never match — see
  §3.6) and added a bounded in-process parse cache
  (`_load_local_osm`) so `get_osm_features` and `get_waterways` share
  one ~145-210s full-file parse instead of each separately paying it —
  both caught and verified live against a real 412MB Nepal `.osm.pbf`
  placed for this purpose.
- Backend: **`building_density`**, an 8th criterion source
  (`app/data/density_raster.py`) and Exposure cluster's first — see
  §3.6. Registered through the same pluggable `register_source()`
  mechanism as every other source (proving Phase 5's own extensibility
  claim again, this time for real rather than a test-only dummy source):
  only `overlay/sources.py` gained a new adapter + registration line,
  nothing about `overlay/compute.py`, `service.py`, `router.py`, or
  `ahp/` changed. Frontend: added to `frontend/src/config/criteria.js`
  under Exposure, closing the gap noted above.
- Frontend: a **visual identity + landing page redesign**, renamed
  **FloodHUB** (matching the project's own GitHub repo name; the
  Kathmandu Valley scope moved to a subtitle/pilot note rather than the
  product name itself) — a design pass only, no data flow/state/API
  changes. `App.jsx` gained a local `view` ('landing' | 'tool') state
  (presentation-only navigation, not part of `AppStateContext`); the
  tool itself (`Sidebar` + `MapView`) is unchanged functionally. New:
  `LandingPage.jsx` (a single centered-column hero — an earlier version
  paired it with an inline-SVG contour illustration, removed at the
  user's request as "not good enough"; a small `Logo.jsx` mark is used
  instead, in both the landing nav and `Sidebar`'s header), and a
  `CreditsSection.jsx` shown both on the landing page and via a
  persistent "About" button in `Sidebar`'s header (`AboutModal.jsx`) so
  it's reachable without leaving the tool. `frontend/src/config/
  attribution.js` holds this content: team cards (name, email,
  LinkedIn, a photo cropped with Pillow to a head-and-shoulders square
  from each person's own full-body original — a plain circular crop of
  a full-body shot would shrink the face to a speck), and the 3
  criterion-source attribution strings copied verbatim from
  `backend/app/data/attribution.py` (no live API call from the landing
  page, since it's shown before any AOI/compute exists — see that
  file's own docstring for the sync caveat) plus HydroBASINS/Nepal-
  boundary credits. Methodology citations (Saaty/AHP, the drainage-
  density technique reference) are still left out for now at the user's
  request ("don't cite papers yet") — a product decision, no longer a
  blocked one. The note previously here said no full bibliographic
  details existed anywhere in this codebase; that was inaccurate. The
  reference method's complete citation was already in
  `backend/tests/test_ahp_core.py` (whose docstring transcribes the
  paper's Tables 4–5), and now also lives in
  `backend/app/data/attribution.py`'s `METHODOLOGY_CITATIONS` and, per
  criterion, in `frontend/src/config/literature.js`'s `REFERENCES`:
  Parajuli, G., Neupane, S., Kunwar, S., Adhikari, R., & Acharya, T. D.
  (2023), *A GIS-Based Evacuation Route Planning in Flood-Susceptible
  Area of Siraha Municipality, Nepal*, ISPRS Int. J. Geo-Inf. 12(7),
  286, https://doi.org/10.3390/ijgi12070286 — open access, CC BY 4.0. `index.css` was rewritten around
  an explicit design-token system (type/spacing/radius/shadow scales, a
  teal/terracotta palette distinct from the risk ramp so UI chrome is
  never mistaken for a risk value, both themes) that every existing
  panel (`AOIPanel`, `CriteriaPanel`, `WeightingPanel`, `ComputePanel`,
  `ResultPanel`, the AHP pairwise editor) reads through — none of those
  component files needed logic changes, since they were already driven
  entirely by class names. Verified with headless-browser screenshots
  across light/dark × landing/tool × every sidebar step, no console/
  page errors.
- Backend: **basin selections are no longer capped to a bounding
  rectangle**, per explicit user request. Two related fixes in
  `app/common/aoi.py` / `app/overlay/compute.py`:
  1. The area cap (`MAX_AREA_KM2`, raised 500 → 1000 km² earlier in this
     phase — real HydroBASINS basins routinely exceeded 500 km²) no
     longer applies at all to any AOI with a true `polygon` set (i.e.
     any basin selection) — only a plain hand-drawn bbox is still
     capped. A basin is a fixed-size real-world unit, not an arbitrary
     rectangle a cap should protect against; documented tradeoff this
     accepts: Nepal has multi-thousand-km² basins, and at 10m
     resolution that's a very large, slow, memory-heavy grid with no
     ceiling today.
  2. The risk surface's own output is now masked to the AOI's true
     polygon shape (`mask_risk_surface_to_polygon`, new in
     `compute.py`, via `AOI.polygon_utm` reprojection + a
     `rasterio.features.rasterize` inside/outside test), not left
     filling the full rectangular grid — previously, even a basin
     selection's *result* always rendered as a rectangle regardless of
     the basin's real shape, since a raster grid is inherently
     rectangular and nothing downstream of Phase 2 ever consulted
     `polygon`. Verified live against a real basin (true area 370 km²
     inside a 2,156 km² bounding box): the masked result came back with
     17.1% valid pixels, matching that ~17% true-shape-to-bbox ratio.
     `compute_cache_key` now folds in the polygon's WKT too, so a basin
     and a same-bbox rectangle can never collide in the risk-surface
     cache. Covered by new hand-verified tests in `test_compute.py`
     (masking math), `test_aoi.py` (`polygon_utm` reprojection, cap
     exemption even when a polygon's true area also exceeds the cap),
     and `test_service.py` (orchestration wiring, mocked).
- Backend: fixed a real transient-failure bug in the DEM/WorldCover
  cloud-fallback fetch (`app/data/dem.py`, `worldcover.py`) — a bare
  `rasterio.open("https://...")` against public S3 has no retry
  configured by default, so an ordinary transient network blip
  ("CURL error: Empty reply from server", reproduced live) surfaced
  straight to the user as a failure. Both now open their datasets
  inside `rasterio.Env(**config.GDAL_HTTP_RETRY_ENV)` (new in
  `config.py`, env-overridable) — GDAL's own HTTP retry, not a hand-
  rolled Python loop. Also fixed: `jenkspy` (added to `requirements.txt`
  in an earlier phase) was missing from the actual running container
  because the image was never rebuilt after that change — Jenks breaks
  were silently 500ing until this was caught and the image rebuilt.
- Backend: **fixed the slow-OSM-lookup problem** (`osm.py`'s local-file
  path took ~145-210s per AOI, since `pyrosm` has no partial/indexed
  read of a raw `.osm.pbf` — it scans+decodes the whole file regardless
  of AOI size). Original plan was to pre-process the `.pbf` into a
  GeoJSON extract and host it on Cloudflare R2, but that got dropped for
  a better one raised by the user: this project's `backend/data/raw/
  osm/` already had a Geofabrik shapefile export (`nepal-260713-
  free.shp/`) sitting alongside the `.pbf`, already split by feature
  type. `osm.py` now has a third, FASTEST local tier ahead of the raw
  `.pbf`: geometry-only FlatGeobuf files (`backend/data/raw/osm/
  processed/{buildings,roads,waterways}.fgb`, built once from that
  shapefile export per that directory's own README — buildings filtered
  to nothing, roads to a driving-network approximation via Geofabrik's
  `fclass` field, waterways to river/stream/canal, matching osm.py's
  existing `WATERWAY_TAGS` exactly), read with a bbox-filtered
  `geopandas.read_file` that uses FlatGeobuf's built-in spatial index.
  Verified live against the real 412MB Nepal `.pbf`/its real Geofabrik
  export: 0.23s for buildings+roads, 0.01s for waterways (was
  145-210s) — a ~600-900x speedup, with the `.pbf`-via-pyrosm tier kept
  as the fallback for a local file dropped in without regenerating these
  extracts, and R2 (config wiring for which was built first, before the
  pivot, and left in place as a legitimate option) staying the fallback
  for a deployment with no local files of either kind. Building the
  pre-processed extract itself surfaced two real, separate infrastructure
  problems worth remembering: (1) the naive version of this — re-parsing
  the whole `.pbf` with `pyrosm` for ALL of Nepal at once, before the
  shapefile-export idea — OOM-killed the backend container (Docker
  Desktop's WSL2 VM is capped at 6.7GB by default); switching to reading
  the already-resolved shapefile geometries directly via `pyogrio`, and
  running the one-time conversion on the HOST Python rather than inside
  the container, avoided this entirely. (2) the host's C: drive was
  found completely full (0 bytes free) mid-session from something
  entirely unrelated to this project (Docker's own footprint here is
  only ~8.5GB) — several backend crashes and a truncated pickle cache
  entry traced back to this before it was caught; `backend/data/
  cache/processed/` is safe to clear entirely if this recurs (regenerable
  output cache, not source data, per its own `.gitignore` comment).
  Also fixed while investigating this: `.gitignore`'s existing
  `!backend/data/raw/**/.gitkeep` / `!backend/data/cache/**/.gitkeep`
  negations had never actually worked (verified with `git check-ignore`
  — a `dir/*` blanket exclude can't be overridden by a `!dir/**/pattern`
  negation for anything nested inside it, a real gitignore limitation,
  not a typo) — nothing under either directory was ever tracked despite
  the clear intent; rewritten as `dir/**` + an explicit directory-level
  `!dir/**/` re-include, which actually works.
- Backend: **9th criterion source, `population_density`** —
  `app/data/population.py`, Meta/CIESIN HRSL population, live windowed
  S3 reads (`s3://dataforgood-fb-data/hrsl-cogs/hrsl_general/hrsl_general-
  latest.vrt`, a single pre-built GDAL virtual-mosaic file — no manual
  per-tile URL templating needed, unlike DEM/WorldCover), same local-
  check-first/cloud-fallback shape as those two sources. Registered via
  the existing `overlay/sources.py` registry mechanism, no changes to
  overlay/compute.py's math or any other Phase 2 source module. Region
  config (`config.POPULATION_S3_REGION_ENV`, `AWS_DEFAULT_REGION=us-
  east-1`) included per explicit request, though live testing during
  implementation showed the plain-HTTPS access pattern used here (same
  as DEM/WorldCover) actually worked without it. Frontend: added to
  `criteria.js`'s Exposure cluster alongside `building_density`
  (Exposure's first occupant, from an earlier phase); `dist_to_river`
  confirmed already correctly in Hydrological, not moved. This is also
  the source that prompted the count-vs-density resampling rule now
  documented in §2.2 above — HRSL's per-pixel value is a population
  COUNT, not a density, and an early version of this source bilinear-
  resampled it directly (wrong per that rule, caught and fixed before
  first commit — see `population.py`'s `_count_to_density`).
- Backend: **fixed a real correctness bug in the risk-surface cache
  key** (`overlay/compute.py`'s `compute_cache_key`) — it hashed only
  `criterion_id` + `weight`, never the criterion's own
  `reclassification_rules`. Two requests for the same AOI/criterion_id/
  weight but genuinely different rules (e.g. the frontend's
  classification editor submitting custom breaks) collided on the same
  `cache_key` and silently served each other's cached result — caught
  live: two manual test requests with different breakpoints for the
  same criterion produced an identical `cache_key`. Fixed by folding in
  `reclassify.rules_fingerprint()` per criterion, the same canonical
  hash the *inner* per-criterion reclassification cache
  (`apply_reclassification_cached`) already correctly used — reused
  rather than re-implemented, so the two caches can never disagree
  about what counts as "the same rules." Audited every other cache-key
  computation in the codebase for the same gap while at it: `reclassify.
  py` was already correct (where the reusable fix came from);
  `data/cache.py`'s generic `cached_or_compute` has no bug of its own
  (it faithfully uses whatever `version` string it's given — the gap was
  entirely in what `compute_cache_key` computed for that argument); every
  raw-source fetch (DEM/WorldCover/OSM/population/hydrology/etc.)
  correctly caches on AOI alone, with no criterion-specific config in
  play at that layer; `AOI.cache_key()` has no bug either (deliberately
  AOI-only by design — the risk-surface cache's polygon-awareness lives
  in `compute_cache_key`'s own hash instead, confirmed still correct),
  though its docstring had gone stale claiming "every consumer only
  reads bbox_4326" and was corrected alongside. `schemas/
  risk_surface.schema.json`'s `criteria_set` items now require
  `reclassification_rules` too, matching what the key actually depends
  on (not yet wired into any live API response — currently internal to
  compute.py/service.py's own hashing — updated for documentation
  accuracy regardless).
- Backend: **vulnerability classification + computation reporting**,
  hazard-zone exposure interpretation (buildings classified by which
  discrete 1-5 hazard class they fall in — matching the Siraha/Lee et
  al. approach; NOT a separate building-quality/susceptibility
  dimension). Four new small modules under `app/overlay/`, each one
  part of the pipeline:
  - `hazard_classes.py`: inverts risk_surface's own R_norm = (R-1)/(5-1)
    formula (R in [1,5], the un-normalized weighted-sum score) back into
    discrete classes 1-5, ROUND-NEAREST (not floor — floor would
    systematically bias every pixel down by up to just-under-1 whole
    class). Labels: 1=Very Low … 5=Very High. This is a
    re-discretization of a continuous COMPOSITE score blended across
    however many criteria contributed at that pixel, not "recovering" a
    single lost per-pixel class — standard practice for this kind of
    report, documented explicitly so it's never mistaken for the latter.
  - `building_classification.py`: tags each OSM building with the
    hazard class its footprint falls in, via MAJORITY-OVERLAP (not
    centroid) — a large/elongated building can genuinely straddle a
    class boundary at this project's 10m resolution, and centroid
    sampling would report whichever class happens to contain one
    arbitrary point. Implemented as ONE labeled rasterize pass (every
    building's footprint burned into a single "which building owns this
    pixel" raster at once) + one vectorized groupby-mode, not a per-
    building rasterize loop — verified live over a real ~28 km² AOI
    (87,402 real buildings) without becoming the bottleneck. Ties
    resolve to the higher class (never understate risk); a footprint
    too small to rasterize to any pixel falls back to a direct centroid
    sample rather than going unclassified.
  - `zonal_stats.py`: per-hazard-class area/population/building-count.
    Population is Σ(density × pixel_area_km²) over each class's pixels
    — NOT a raw Σ(density) — the same count-vs-density unit correction
    established for population.py earlier this phase, one layer up.
  - `report.py`: assembles the full report — AOI (bbox/polygon/area_km²/
    basin id+support_status if supplied), the actual submitted criteria
    (id/source/reclassification_rules, fully generic over however many
    were requested — never a fixed/assumed set), weighting (method +
    the real AHP pairwise-matrix breakdown when applicable), the Part 3
    zonal table, and headline figures (totals, and the count/% in
    hazard classes 4-5 specifically). A criterion's display `name` and
    `cluster` aren't backend concepts at all (frontend/src/config/
    criteria.js is the only place either currently lives) — `name` is
    an optional pass-through on the report request, defaulting to the
    criterion's own id; `cluster` is derived from the AHP breakdown's
    own within_cluster_comparisons when weighting.method='ahp' (the
    only place the backend can know it), null under equal weighting.
  - **Exposed as `POST /api/overlay/report`, a separate endpoint, NOT a
    bare `GET` by cache_key** — the weighting section (AHP pairwise
    matrices, consistency ratios) genuinely isn't derivable from
    cache_key alone, since the base overlay engine (`compute_overlay`)
    only ever receives the final flat weights, never AHP-level detail;
    this is a real architectural fact, not a style preference. Reuses
    `compute_overlay`'s own risk-surface cache untouched (a report
    request for already-computed params is a cache hit there, not a
    recompute); the heavier new work (hazard classes, building spatial
    join, zonal stats) is cached separately under the SAME cache_key.
    **New cross-phase dependency, confirmed as a deliberate architectural
    decision, not silent drift**: Phase 1 (AHP) and Phase 2/3 (data
    layer/overlay) had been kept strictly decoupled until now (the base
    overlay engine only ever received AHP's *output* — flat
    `final_weights` — never anything upstream of it). This feature
    breaks that: `overlay/models.py` imports AHP's Pydantic shapes
    (`PairwiseMatrixInput`, `PairwiseResultOut`), and — the part that
    actually matters here, not just borrowed type definitions —
    `overlay/report.py` imports and calls `app.ahp.hierarchy.
    compute_hierarchy` directly, i.e. **the overlay layer now depends on
    AHP's actual computation**, not merely its data shapes. Accepted
    because the alternative (re-deriving eigenvector weights/consistency
    ratios independently inside `overlay/`) would risk the two
    implementations silently diverging over time; reusing the one real
    implementation guarantees they can't. A future refactor that further
    separates these phases needs to account for this dependency
    explicitly, not rediscover it.
  - **A cheap, deliberate consistency check between `final_weights` and
    the recomputed AHP breakdown**, added after review: nothing
    otherwise forces the two to agree — a caller could submit stale
    `final_weights` alongside freshly edited pairwise matrices, and the
    report displays both. `report._weighting_consistency_warning`
    compares `final_weights` against `compute_hierarchy`'s own
    freshly-recomputed `final_weights` (tolerance `1e-6`, matching this
    codebase's existing floating-point-equality convention —
    `compute.py`'s `_WEIGHT_SUM_TOLERANCE`, `ahp/constants.py`'s
    `VALIDATION_TOLERANCE`) and flags either a numeric discrepancy or a
    mismatched criterion-id set. Never raises and never changes the
    computed risk surface (still computed from `final_weights` exactly
    as submitted, same trust model `POST /compute` already has) — surfaced
    as `weighting.consistency_warning` (`null` when they agree, or under
    equal weighting, where there's nothing to cross-check) purely so a
    silent mismatch can never quietly undermine the report's own
    credibility. **Renormalizes the recomputed AHP weights before
    comparing** — caught while wiring up the frontend, not in the
    original design: `frontend/src/state/AppStateContext.jsx`'s
    `useFinalWeights` (AHP mode) renormalizes `compute_hierarchy`'s raw
    per-criterion weights over just the currently-*selected* criteria
    whenever some canonical cluster has none selected (a normal,
    explicitly-supported case, not an edge case — see this file's own
    note on Exposure sometimes being empty) before ever submitting to
    `POST /compute`, since an incomplete AHP hierarchy's raw weights
    don't sum to 1 on their own and `compute_risk_surface` always
    requires exactly that. Comparing this endpoint's own fresh
    `compute_hierarchy` recompute against `final_weights` *without* the
    same renormalization would have flagged that everyday case as a
    false "mismatch" on every partial-cluster-coverage request — the
    single most common real usage pattern, not a rare one. Fixed by
    renormalizing the recomputed weights over their own total before
    comparing (a no-op when every cluster is already covered, since that
    total is already ~1) — verified live end to end via the actual
    frontend flow after the fix, not just in tests.
  - **`GET /api/overlay/hazard_classes/{cache_key}.tif`**: the discrete
    1-5 hazard-class raster as a standalone downloadable GeoTIFF — often
    what a user actually wants for GIS use, more than the continuous
    surface. Deliberately NOT tied to POST /report at all: derived and
    materialized lazily on first request straight from the already-
    materialized risk_surface .tif for that cache_key (no AOI needed,
    no recompute) — reachable immediately after a plain POST /compute,
    whose own response now also advertises this URL
    (`hazard_classes_data_url`) alongside the existing risk-surface one.
  - Verified live end to end against the real running backend, not just
    tests: a real 2-criterion report over a real ~28 km² AOI (48,139 of
    87,402 real buildings classified — the rest correctly unclassified
    where population_density itself has real coverage gaps, propagating
    through risk_surface's own any-nodata-poisons-the-pixel rule), 5
    zonal classes with real area/population/building figures, and the
    hazard-class GeoTIFF downloading correctly from that same run.
  - 41 new tests (hazard-class bucketing incl. the round-vs-floor
    boundary case; zonal-stats density×area math incl. the "would have
    been off by ~10,000x" regression case; building classification's
    majority-vs-centroid disagreement case, hand-constructed so the two
    rules provably give different answers, plus a genuine tie and both
    small-footprint/outside-AOI fallbacks; report assembly in both
    equal- and AHP-weighting modes; the final_weights-vs-recomputed-AHP
    consistency check's match/diverge/mismatched-criteria cases; a full
    real-fixtures integration test through Phase 1-4). 270 backend tests
    passing total, zero regressions. Also fixed while in this area: `tests/overlay/
    conftest.py` had the same `LOCAL_OSM_PROCESSED_DIR`/
    `LOCAL_POPULATION_DIR` test-isolation gap `tests/data/conftest.py`
    was caught and fixed for earlier this phase — report.py calls
    `get_osm_features`/`get_population` directly (not through
    resolve_criterion_raster, unlike every other test in this suite),
    so it needed the same isolation.
- Frontend: exposed the vulnerability-classification/report feature —
  two pieces, both gated on a successful compute (`state.overlay.status
  === 'loaded'`), added in the same pass at the user's request after an
  initial backend-only implementation left nothing in the UI to trigger
  either endpoint.
  - `ResultPanel.jsx`: "Download risk surface (.tif)" / "Download hazard
    classes (.tif)" links, straight from the existing compute
    response's `data_url`/`hazard_classes_data_url` (`api/client.js`'s
    new `absoluteDataUrl` — a plain `<a href>` needs the full backend
    origin, unlike `fetchRiskSurfaceBytes`'s own internal `fetch()`; a
    cross-origin anchor click is a normal top-level navigation, not a
    script-initiated read, so the backend's `Content-Disposition:
    attachment` header triggers a real download with no CORS
    involvement either way).
  - New `ReportPanel.jsx`, a new "5. Vulnerability report" sidebar
    section: a "Generate report" button that assembles `POST
    /api/overlay/report`'s request from state already captured at
    compute time (`criteriaUsed`/`weightsUsed` — the exact snapshot
    `ResultPanel` already reads, so the report can never describe a
    different result than what's on screen) plus what only the frontend
    knows and the backend has no registry for: each criterion's display
    `name` (`config/criteria.js`), the weighting `method` (`equal` |
    `ahp` | `manual` — see below), the raw AHP pairwise matrices
    (`state.ahpMatrices`, already the exact shape the endpoint expects)
    when relevant, and `hybas_id`/`support_status` for a basin-derived
    AOI (looked up from the already-loaded basins GeoJSON by id, not
    tracked as its own state field). Renders the zonal-stats table,
    high-risk headline figures, the weighting breakdown (surfacing
    `consistency_warning` as a visible inline warning when present), and
    its own copy of the two download links (the report's own
    `risk_surface_data_url`/`hazard_classes_data_url`, not assumed
    identical to `ResultPanel`'s — same cache_key in practice, but
    fetched independently rather than threaded through as a prop).
    Individual buildings from the report's GeoJSON are NOT rendered on
    the map (a real AOI can return tens of thousands — verified live
    earlier in this phase, 87,402 for one ~28 km² test case — a map
    overlay at that scale is its own real feature, not a natural
    extension of this pass).
  - **`ReportWeightingInput.method` widened to accept `"manual"`**,
    alongside the `"equal"`/`"ahp"` the brief named explicitly — the
    frontend has a third weighting mode (raw typed weights, normalized;
    `state.weightMode === 'manual'`), and mislabeling it as `"equal"` in
    the request would misrepresent how the weights were actually
    produced in the report meant to explain exactly that.
  - Verified live end to end through the real running app (not just a
    backend curl check): drew an AOI, selected a criterion, computed,
    confirmed both `ResultPanel` download links work, generated a
    report, and confirmed every section renders correctly — headline
    stats, the 5-row zonal table, "Method: equal" with no
    `consistency_warning` shown (correctly, since equal weighting has
    nothing to cross-check) — with zero browser console errors
    throughout.
- Backend: **fixed a real bug — `population_density` left a ~50%,
  speckled gap pattern in the risk surface**, reported live and traced
  to root cause. Not a reprojection/resampling artifact (checked the
  raw HRSL source directly, before any reprojection in this pipeline —
  the same ~48-50% nodata rate was already there, even deep in central
  Kathmandu's built-up core). The actual cause: HRSL's own data model
  assigns a population value ONLY to pixels its settlement classifier
  detected as built-up, deliberately leaving non-settlement pixels
  (roads, gaps, unbuilt land — entirely normal at 30m resolution even
  in a dense city) without a value, rather than an explicit 0 (Yetman,
  HRSL technical presentation, IUSSP — CIESIN/Meta's own documentation:
  "zeroes indicate not-settled areas" in HRSL's settlement-classification
  step). This pipeline was treating that nodata as "unknown", which
  then poisoned the FINAL risk surface at that pixel
  (compute_risk_surface's any-nodata-poisons-the-pixel rule) — using
  population_density as a criterion meant roughly half of any AOI got
  no risk score at all. Fixed in `population.py`'s `_count_to_density`:
  HRSL nodata now becomes a confirmed density of 0 (Nepal is always
  within HRSL's real global coverage, so this reading is correct here),
  not a value propagated as output nodata. Verified live, before/after,
  against the real bucket over the same AOI: risk-surface nodata dropped
  from 49.97% to 3.18% (the residual is genuine reprojection-edge
  nodata — grid cells outside the actual read window's real footprint —
  a different, legitimate case, untouched by this fix). 2 existing
  `_count_to_density` tests updated to assert the new (correct)
  zero-not-nodata behavior; 271 backend tests passing, zero regressions.
- Frontend: **basemap toggle + 3 additional free basemaps**. New
  `MapView.jsx` `BasemapControl` (a plain MapLibre `IControl`, top-left,
  next to the existing zoom control) — a dropdown among 5 providers
  (Street/OSM, Light/CARTO Positron, Dark/CARTO Dark Matter, Satellite/
  Esri World Imagery, Topographic/OpenTopoMap) plus a show/hide toggle
  for the basemap layer entirely (useful to see just the risk-surface/
  AOI/basin layers without street-map clutter underneath). Independent
  of the app's own light/dark theme now (previously the map's tiles
  were tied 1:1 to `state.theme`) — `state.basemapStyle`/
  `basemapVisible` are their own state, defaulted from the initial
  theme purely so first paint looks coherent, not coupled after that.
  Every new provider was verified live before being added (a real tile
  fetch confirmed as a genuine 256x256 image, not an error page with a
  200 status — the same diligence this project's original OSM/CARTO
  pair already had) — CARTO Voyager and Esri's own topographic style
  were also verified live but left out as redundant with Street and
  OpenTopoMap respectively, to keep the picker to a genuinely
  differentiated set rather than every option merely because it's free.
  Switching providers fully removes+re-adds the raster source/layer
  (not just `setTiles()` on one persistent source) specifically so
  MapLibre's `AttributionControl` picks up each provider's own required
  credit line — Esri's and OpenTopoMap's licenses require different
  attribution text than OSM/CARTO's, verified live that the displayed
  attribution actually changes per provider, not just the tiles.
- Backend + frontend: **real compute progress**, not a fabricated/
  animated bar. `POST /api/overlay/compute` remains completely
  unchanged (still a plain JSON request/response — any non-interactive
  API caller, and `report.py`'s own internal reuse of `compute_overlay`,
  are unaffected); a new sibling `POST /api/overlay/compute/stream`
  streams real Server-Sent Events as `compute_overlay` actually does the
  work. `compute_overlay` gained one additive parameter,
  `on_progress: Callable[[str], None] | None = None` (default `None` —
  every existing caller is byte-for-byte unaffected), called at each
  meaningful step: cache check, before/after resolving each criterion
  (`"Resolving {id} ({i}/{n}, source: {source})…"`), combining into the
  risk surface, masking to a basin's true shape (only when the AOI has
  a polygon), writing the GeoTIFF, and a final `"Done."`. New
  `progress_stream.py` bridges that synchronous callback out to SSE: a
  plain Python generator can't `yield` from a callback several calls
  deep inside an already-executing frame, so `compute_overlay` runs in
  a background thread (pushing messages onto a `queue.Queue`) while the
  route handler's own generator polls that queue and yields each
  message as it arrives — the route handler is already a plain
  (non-`async`) `def`, which FastAPI runs in its own worker thread
  automatically, so no asyncio-level bridging was needed on top of
  that. Terminates in exactly one `{"type": "done", "result": ...}`
  (same shape `POST /compute`'s own body has) or
  `{"type": "error", "error": str, "message": str}` — an SSE response's
  HTTP status is always 200 by the time streaming starts, so errors
  (including a bare `except Exception`, deliberately never silently
  swallowed) surface in-band rather than as a 4xx/5xx the way `POST
  /compute` itself still does. Frontend: `api/client.js`'s new
  `computeOverlayStream` (a plain `fetch()` + manual SSE-frame parsing —
  the browser's native `EventSource` only supports GET with no body,
  and this needs POST with a JSON payload; kept dependency-free rather
  than pulling in an SSE library for one endpoint) replaces
  `ComputePanel.jsx`'s use of the plain `computeOverlay`. Each progress
  message is appended to a new `state.overlay.progressLog` (a new
  `OVERLAY_PROGRESS` action; reset only on `OVERLAY_LOADING`, kept
  through `LOADED`/`ERROR` so the finished log stays visible) and
  rendered live as a checklist below the compute button, auto-scrolled
  to the latest entry. Verified live end to end, not just in tests: a
  real `curl --no-buffer` capture of the raw SSE bytes showed genuinely
  time-spaced events (not all arriving in the same instant, which would
  indicate silent buffering), and the real running frontend showed the
  log populating and auto-scrolling correctly during a real compute.
  9 new backend tests (the callback's own call sequence and cache-hit
  short-circuit in `test_service.py`, the SSE event generator's success/
  validation-error/data-source-error/unexpected-exception paths in the
  new `test_progress_stream.py`, and the actual HTTP streaming response
  in `test_router.py`) — 281 backend tests passing total, zero
  regressions.
- Frontend: **visual redesign — "midnight precision instrument"**
  (Linear-referenced), a presentation-layer pass per this project's own
  established discipline ("a design pass only, no data flow/state/API
  changes" — see the earlier visual-identity redesign phase, above).
  `AppStateContext.jsx`'s state shape, `api/client.js`, and every backend
  file are untouched except one deliberate one-line change:
  `initialTheme()` now defaults to dark for a first-time visitor
  (matching a "dark-first" product decision) rather than following the
  OS's `prefers-color-scheme`, still fully overridable via the existing
  toggle and persisted the same way as before. `index.css`'s token
  system was rewritten around a dark-as-default palette (near-black
  canvas, hairline-border elevation instead of shadows, a single teal-
  cyan accent per view — terracotta demoted to a rare highlight rather
  than a second competing interactive color), a light theme rebuilt
  under the same structural rules, and a new `--font-mono` token
  (JetBrains Mono) for tabular/technical data — filling a gap the
  previous session's own handoff document had flagged. `Sidebar.jsx`'s
  plain numbered cards became a connected step-rail (new
  `StepSection.jsx`: numbered marker + connecting line, complete/active/
  locked states, click-to-collapse) — every reachable step defaults
  *open*, not auto-collapsing on completion: an early version collapsed
  a step the instant it became "complete," which for the Criteria step
  meant the checkbox list vanished after just one checkbox was checked
  (the same threshold that unlocks Weighting) — caught via testing, not
  assumed. `MapView.jsx` gained two genuinely new map controls previously
  absent (a live coordinate/zoom readout and MapLibre's own
  `ScaleControl`) alongside restyled zoom/basemap/attribution chrome.
  `ResultPanel.jsx`'s risk-ramp legend was redrawn as a smooth gradient
  with tick labels (was a 5-banded flex bar); `ReportPanel.jsx`'s stat
  cards moved to a thin-accent-rule/mono-numeral treatment and its zonal
  table gained per-hazard-class color swatches, reusing the existing
  `riskValueToRgb` function rather than introducing a new color source.
  Verified end to end via Playwright-in-Docker against the real running
  app: the full AOI → criteria → AHP weighting → compute → report flow,
  both themes, real backend data, zero console errors. Backend test
  suite unaffected (281 passed, unchanged, since nothing backend-side
  was touched).
- Backend: **10th criterion source, `hand`** (Height Above Nearest
  Drainage) — `app/data/hydrology.py`, registered via the existing
  pluggable `register_source()` mechanism with zero changes to
  `overlay/compute.py`, `service.py`, `router.py`, or `ahp/`. Computed
  via **pysheds' own `compute_hand`** (not a hand-rolled flow-path
  descent — it matched the existing `_DIRMAP`/Raster/ViewFinder
  conventions `_run_pysheds_pipeline` already established cleanly enough
  that reimplementing it would only add a second, possibly-inconsistent
  D8 convention), reusing rather than recomputing every piece of the
  existing hydrological pipeline: `_run_pysheds_pipeline` now also
  returns the conditioned (sink-filled) DEM (`FlowAccumulationResult`
  gained an `elevation_conditioned` field, default `None` so every
  existing TWI/drainage_density test fake keeps working unchanged), and
  `get_hand` reuses `compute_flow_accumulation`'s cached flow-direction
  grid, conditioned DEM, and — deliberately — `drainage_density`'s own
  `config.DRAINAGE_DENSITY_THRESHOLD_CELLS` stream-network threshold
  (the same synthetic stream network both measure against, a real shared
  dependency, not a coincidence: HAND is only as meaningful as the
  stream network it's measured against, and this project has exactly
  one). A real, previously-undocumented finding from hand-verifying this
  against actual pysheds output: **the outer 1-pixel ring of any grid
  can never resolve** (no full D8 neighborhood to trace through,
  confirmed on synthetic grids from 5×5 to 11×11) — stricter than flow
  accumulation's own "may be underestimated near the edges"
  (`EDGE_RELIABILITY_WARNING`, reused verbatim for `hand` rather than a
  new warning channel, per an explicit decision to confirm — its wording
  slightly undersells HAND's actual edge behavior, which is nodata
  outright, not underestimated). Low HAND means high risk; that
  inversion is handled entirely at the reclassification-rules level
  (`frontend/src/config/criteria.js`'s `hand` entry, `riskDirection:
  'descending'`, Hydrological cluster, placeholder equal-interval breaks
  in the same not-yet-calibrated spirit as `drainage_density`'s own).
  8 new tests in `tests/data/test_hydrology.py` (hand-verified elevation-
  above-stream values on the existing V-shaped-valley DEM, including an
  on-stream pixel at ~0 and two off-stream pixels via different flow
  paths; the edge-unresolvability behavior; shared-preprocessing reuse,
  proven by counting real pipeline invocations across two sources for
  the same AOI; basin-vs-bbox warning propagation; cache-busting on
  threshold change) plus a new registry-consumption test in
  `tests/overlay/test_sources.py` — 288 backend tests passing total
  (281 + 7 net new), zero regressions. Also verified live end to end
  against the real running backend over a real ~30 km² Kathmandu AOI
  (90% valid-pixel coverage, values in the expected range).
- Backend: **investigated and documented a second, larger `hand` gap
  mechanism**, prompted by a user report of a visible branching gap
  pattern in a rendered `hand` risk surface over the full Kathmandu
  Valley — see §3.6's `hand` section for the full write-up. Distinct
  from the outer-1-pixel-ring finding above (a purely geometric effect):
  an internal pit DEM conditioning didn't fully resolve breaks HAND for
  its entire upstream contributing area, not just itself, since HAND
  needs a full downstream trace to succeed while flow accumulation only
  needs a cell's own upstream sum. Measured live on the real ~1518×1550
  grid: ~12% nodata (vs. ~3% base-invalid) — confirmed, not assumed, by
  manually tracing 15 sampled gap cells' D8 paths step-by-step; every
  one terminated at an unresolved intermediate cell, never the grid
  edge. Reproduced deterministically with a new test,
  `test_internal_unresolved_pit_propagates_nodata_upstream`. **Decision,
  confirmed with the user**: documented as a known limitation, not
  fixed — a fix would mean either changing DEM conditioning (risking
  `twi`/`drainage_density`'s own results, which reuse the same
  conditioned DEM) or redefining what counts as a valid drainage
  reference, both real methodology choices for a future phase, not bug
  fixes. One new deterministic regression test added for this specific
  mechanism (`test_internal_unresolved_pit_propagates_nodata_upstream`)
  — 8 tests now cover `hand` specifically, 289 backend tests passing
  total, zero regressions.
- Backend + frontend: **user-selectable stream-network threshold** — the
  user, having just had `drainage_density`/`hand`'s shared synthetic
  stream network explained, asked to make its threshold selectable from
  the UI rather than a fixed deployment-wide env var. See §3.6's
  `drainage_density` section for the full backend write-up (the new
  `stream_threshold_cells` field threaded additively through
  `overlay/models.py`/`service.py`/`sources.py`/`breaks.py`/
  `hydrology.py`, and the cache-key bug this surfaced and fixed).
  Frontend: **one shared control**, not per-criterion — `drainage_density`
  and `hand` are measured against the exact same stream network, so
  letting them diverge would be scientifically inconsistent between the
  two results in a single compute (`state.streamThresholdCells`,
  `config/criteria.js`'s new `STREAM_THRESHOLD_SOURCE_IDS` the one place
  both `CriteriaPanel`/`ComputePanel`/`ClassificationEditor` read from).
  `CriteriaPanel.jsx` renders it once, below the checkbox list, when
  either criterion is checked, with a live "≈ X km² contributing area"
  helper computed from the fixed 10m grid resolution.
  `ClassificationEditor.jsx`'s "Customize breaks" preview re-fetches
  automatically when the threshold changes (a new reducer case,
  `SET_STREAM_THRESHOLD_CELLS`, resets just those two criteria's
  breaks-fetch status back to `idle`, the same mechanism an AOI change
  already relies on) — verified live the preview genuinely changes (e.g.
  one real test AOI: data range 0.00–5.11, breaks ~[1.02, 2.04, 3.07,
  4.09] at the default 500-cell threshold vs. 1.20–10.31, ~[3.02, 4.84,
  6.67, 8.49] at 50 cells — a lower threshold picks up more/smaller
  tributaries, correctly raising both ends of the range). **A real bug
  caught during this same verification pass**: `ReportPanel.jsx` rebuilds
  its own `criteria` array field-by-field from `criteriaUsed` rather than
  spreading it, so `stream_threshold_cells` would have been silently
  dropped from every report request — fixed before it shipped. 6 new
  backend tests (cache-key, both hydrology functions' override behavior,
  the breaks endpoint's forwarding, and the registry adapters' forwarding
  including a check that unrelated sources ignore the extra kwarg
  without error) — 295 backend tests passing total, zero regressions.
  Verified live end to end via Playwright-in-Docker against the real
  running app, not just in tests: the shared control renders/updates
  correctly, and two full computes at different thresholds produced two
  different `cache_key`s as expected.
- Backend + frontend: **per-criterion raster snapshots**, unlocked by the
  vulnerability report — the user wanted to see each individual
  criterion's own raster, not just the combined weighted risk surface.
  Initially proposed as "only frontend needs changes"; investigated and
  reported back that the bytes don't exist anywhere the browser can
  reach today (each criterion's reclassified raster is computed
  in-memory inside `compute_overlay`'s per-criterion loop and discarded
  once the combined surface is built), so a small backend addition was
  necessary. Discussed the storage/latency tradeoffs with the user
  before building anything; **explicit scoping decision from the user**:
  snapshots are only available after generating the report, never after
  a plain compute — which also resolves the storage-growth concern for
  free, since report generation is already a deliberate, opt-in action.
  See §3.4's own "Per-criterion raster snapshots" entry for the field-
  level contract.
  - Backend: `overlay/service.py`'s `OverlayResult` gained a
    `criterion_rasters` field carrying what the per-criterion loop
    already computes (no new computation, just no longer discarding it)
    — `POST /compute`'s own response deliberately never reads it, so its
    contract is byte-for-byte unchanged. `overlay/report.py`'s new
    `_materialize_criterion_rasters` is the *only* place these ever get
    written to disk (reusing the already-existing
    `write_hazard_class_geotiff`, since a reclassified criterion raster
    is byte-for-byte the same shape/dtype/nodata convention as a
    hazard-class raster — no new writer needed), masked to a basin AOI's
    true polygon shape via a new shared `_mask_array_to_polygon` helper
    extracted from `mask_risk_surface_to_polygon`'s own core logic. New
    route `GET /api/overlay/criterion_raster/{cache_key}/{criterion_id}
    .tif` mirrors the existing risk_surface/hazard_classes routes
    exactly, 404ing until a report exists for that `cache_key` — this is
    what actually enforces "only after the report", not a UI-layer
    convention. **A real path-traversal gap closed alongside this**:
    `OverlayCriterionInput.id` (previously an arbitrary caller-chosen
    string with no format constraint) is now restricted to a safe
    filename charset, since this is the first feature to ever use `id`
    to build a filesystem path — doesn't change any real existing
    behavior, since the frontend has only ever sent `id == source`.
    8 new backend tests (criterion_rasters population, materialization/
    no-rewrite-on-second-request/polygon-masking in report.py, the new
    route's 404-before/200-after/path-traversal-rejection behavior, the
    `id` charset rejection) — 303 backend tests passing total, zero
    regressions.
  - Frontend: the GeoTIFF-decode-to-canvas-dataURL logic that used to
    live only inline in `MapView.jsx`'s risk-surface layer was extracted
    into a shared `lib/rasterPreview.js` (`decodeGeoTiffToDataUrl`),
    parameterized by a color function and an optional downsample target
    size — thumbnails decode via geotiff.js's own `readRasters({width,
    height, resampleMethod: 'nearest'})` rather than full-resolution
    decode + scale-down, `'nearest'` specifically (never bilinear) per
    this project's own established categorical-data resampling rule
    (§2.2), since these are discrete 1-5 classes. `MapView.jsx` itself
    now calls this same helper for its own layer — pure de-duplication,
    no behavior change. New `components/CriterionSnapshot.jsx` renders a
    small colored thumbnail + 1-5 legend (reusing `colorRamp.js`'s
    existing `riskValueToRgb((class - 1) / 4)` convention, the same one
    the zonal-stats-table swatches already use — no new palette),
    mounted lazily: only while its containing `<details>` is open, so a
    report with many criteria never decodes rasters nobody looks at.
    `ReportPanel.jsx`'s previously-flat per-criterion weight list became
    expandable entries, each holding a snapshot and its own download
    link. Verified live end to end via Playwright-in-Docker against the
    real running app: a plain compute has no criterion-raster URL at all
    (confirmed 404), generating the report makes one appear and actually
    serves a real GeoTIFF, the UI renders a correct thumbnail/legend/
    working download link, zero console errors.
- Backend + frontend: **new criterion source, `soil_infiltration`** —
  the user asked for a next-steps brainstorm (more factors, among other
  ideas), then specifically requested a live-fetchable soil-type/
  infiltration-capacity source; researched and recommended **ISRIC
  SoilGrids 2.0** over HYSOGs250m (a live CMR granules-API check found
  HYSOGs250m's real URLs sit under NASA Earthdata's `/protected/` path,
  requiring Earthdata Login, while a live probe against SoilGrids
  succeeded with zero credentials), then the user said to use it and
  update everything associated with adding a criterion. See §3.6's
  `soil_infiltration` section for the full write-up, including two
  findings specific to this source and not true of any other one in
  this registry: its cloud source's CRS is Interrupted Goode Homolosine,
  not EPSG:4326 (needing an explicit AOI-bbox reprojection into the
  source CRS before windowing, unlike every other cloud source here),
  and its raw int16 value needs a confirmed g/kg→% conversion (÷10, per
  ISRIC's own published conversion-factor table) applied *before*
  nodata-masking, not after (dividing the raw nodata sentinel first would
  silently produce a wrong-but-plausible value instead of being
  recognized as nodata). New `app/data/soil.py` (local-check-first, live
  cloud fallback against ISRIC's own public unauthenticated hosting —
  same shape as `dem.py`/`worldcover.py`/`population.py`), registered as
  `soil_infiltration` in `overlay/sources.py` with zero changes to the
  registry's own dispatch code. Frontend: `config/criteria.js` gained a
  `soil_infiltration` entry (Land Use cluster, alongside
  `worldcover_land_cover`/`ndvi` — surface-characteristic factors
  affecting runoff, not topography or the channel network;
  `riskDirection: 'descending'`, since higher sand content means faster
  drainage and lower risk) — no new frontend component needed, the same
  "just a registry + config entry" shape `hand`/`ndvi` already had. A
  real, live-verified limitation found and documented (not silently
  worked around): this project's own tiny ~0.6km test-fixture AOI
  (Kathmandu Durbar Square) reads back as a 3×4-pixel window at
  SoilGrids' native 250m resolution with **all 12 pixels genuinely
  nodata** — confirmed as a real small-scale SoilGrids coverage gap at
  that exact spot (a wider window across the same valley came back ~74%
  valid), not a bug in this module; the live-network regression test
  uses a wider bbox for this reason, and the gap itself is documented in
  §3.6 as a known limitation a user could hit with a small enough AOI.
  9 new backend tests (`_scale_and_mask`'s scaling and nodata-before-
  scaling correctness, local-hit reprojection through the real
  Homolosine CRS math, processed-cache reuse, cloud fallback both when
  no local dir exists and when it exists but doesn't cover the AOI, the
  shared GDAL retry-env usage, plus a `@pytest.mark.slow` live-network
  test) — 310 backend tests passing total, zero regressions. Verified
  live end to end: a real `resolve_criterion_raster` call against a real
  ~560 km² Kathmandu Valley AOI produced a correctly-shaped, correctly-
  reclassified `uint8` raster with a plausible class distribution
  (~26% nodata, matching the coverage rate measured directly against the
  raw source), and the frontend dev server serves the updated
  `criteria.js` with the new entry present, zero errors.
- Backend + frontend: **swapped the Nepal boundary source (HERMES →
  OCHA/HDX), added HydroBASINS level 9, and added district-based AOI
  selection** — the user removed the gitignored HERMES file, placed the
  new HDX COD-AB shapefile and a HydroBASINS level-9 download themselves,
  and asked for the basin-level and district pieces to be wired up. See
  §3.5 for the full endpoint/schema writeup; summarized here:
  - `app/data/basins.py` generalized from a single hardcoded level to an
    explicit `level` argument (default 8, so every pre-existing caller
    keeps behaving exactly as before) threaded through every public
    function and `GET /api/basins`/`{hybas_id}`/`{hybas_id}/aoi`'s own
    `level` query param — validated against `SUPPORTED_BASIN_LEVELS`
    (a 422 for anything else, checked by hand rather than typed as
    `Literal[8, 9]`: this FastAPI/Pydantic version's Literal validation
    doesn't coerce a query string like `"9"` into `9`, which was caught
    live — every level=8/level=9 request 422'd until this was found and
    fixed). `config.LOCAL_BASINS_LEV09_PATH` (env override
    `BASINS_LEV09_SHAPEFILE_PATH`) is the new level-9 file's path,
    alongside the existing level-8 `LOCAL_BASINS_PATH`.
  - New `app/data/districts.py` + `app/districts/` (mirroring
    `basins.py`/`app/basins/`'s own split exactly) for Nepal's 77
    districts, reading the HDX file's admin-level-2 layer
    (`config.LOCAL_ADMIN_DISTRICTS_PATH`). `district_to_aoi` produces the
    same `AOI` shape `basin_to_aoi` does, so every existing polygon-aware
    behavior (area-cap exemption, true-shape risk-surface masking,
    hydrology's basin-vs-bbox flow-accumulation clipping) applies to a
    district selection automatically, with zero district-specific code
    anywhere downstream.
  - `config.LOCAL_NEPAL_BOUNDARY_PATH`'s default now points at the HDX
    file's admin-level-0 layer instead of the removed HERMES file;
    GADM was evaluated as an alternative boundary source too (per an
    earlier conversation) and rejected for the same reason HERMES was
    being replaced — its license is non-commercial-use-only as well, so
    it wouldn't actually have fixed the underlying licensing gap.
  - Frontend: `AOIPanel.jsx` gained a third "Select district" tab
    alongside "Draw area"/"Select basin" (now a `mode-toggle--triple`,
    the same 3-button toggle style the weighting-mode picker already
    established) and, within "Select basin", a level 8/9 sub-toggle
    (new `.mode-toggle--sub` CSS, visually subordinate to the top-level
    tabs). `AppStateContext.jsx` gained `basinLevel` (resets the basins
    fetch back to `'idle'` on change, so switching levels re-fetches
    the same way an AOI change already resets classification) and a
    `districts` status slice mirroring `basins`'s own shape.
    `MapView.jsx` gained a districts GeoJSON layer (flat-colored — a
    district has no `support_status` concept — new
    `DISTRICT_FILL_COLOR` in `lib/colorRamp.js`) mirroring the basins
    layer's click-to-select/highlight-selected behavior, and the basins
    click handler now reads `level` off the clicked feature's own
    properties (baked in by `BasinFeatureProperties.level`) rather than
    off possibly-stale component state, so it's correct even in the
    instant right after a level switch.
  - 20 new backend tests (level 8/9 lookup, cross-level ID isolation —
    a level-8 ID genuinely 404s at level 9 and vice versa, confirming
    `level` really selects which file is searched rather than being
    accepted and ignored — invalid-level rejection, `reset_basins_cache`
    clearing both levels at once, plus the full district-module/router
    suite mirroring `test_basins.py`/`tests/basins/`'s own coverage
    including a district-derived-AOI-vs-equivalent-bbox-AOI parity test
    against the real unmodified DEM/WorldCover fetch functions) — 338
    backend tests passing total, zero regressions. Verified live end to
    end against the real placed data (not just the synthetic fixtures):
    `GET /api/basins` returns 547 real level-8 / 1,495 real level-9
    basins, `GET /api/districts` returns exactly Nepal's real 77
    districts with correct names/provinces, an invalid `level` 422s, and
    a district's `/aoi` response round-trips into `AOIInput` correctly.
    Frontend verified via a clean `vite build` (catches import/syntax
    errors across every edited file) and a headless-browser load of the
    dev server with zero console errors; a full interactive click-through
    of the new tabs was not run in this pass (no Playwright/Puppeteer
    tooling was available in this environment) — worth a follow-up
    Playwright-in-Docker pass before relying on this the way earlier
    UI phases' own headless-browser verification did.
- Frontend: **fixed a real layer-visibility bug** in the basin/district
  AOI-selection tabs above, caught by the user through actual
  interaction — exactly the class of bug the previous entry's own
  "no interactive click-through was run" caveat flagged as a risk.
  `MapView.jsx`'s basins/districts MapLibre layers are created lazily,
  once, the first time each tab's data arrives (`state.basins.data` /
  `state.districts.data`); every later visit to that tab just calls
  `setData` on the same already-visible layer. Nothing ever hid a layer
  again once created, so (a) switching from "Select basin" back to
  "Draw area" left the basin polygons rendered over the map
  indefinitely, and (b) switching from "Select basin" straight to
  "Select district" showed both layers overlaid at once. Fixed with a
  new effect that sets each layer set's MapLibre `visibility` layout
  property from `state.aoiMode` directly (`'basin'` shows only the
  basins layers, `'district'` only the districts layers, `'draw'`
  neither) — the single place that reconciles visibility with the
  active mode, independent of when each layer happened to be created;
  each `addLayer` call also now sets its own correct initial
  `visibility` at creation time (covering the edge case where a layer
  is created, via a deferred map `'load'` event, after the user has
  already switched to a different tab). Verified via a clean `vite
  build` and a headless-browser reload with zero console errors: no
  automated test previously existed for this UI-only interaction path,
  and none was added here either (this project's frontend has no
  Playwright/Puppeteer harness set up yet — see the previous entry).
- Frontend: **updated the additional-source credits text**
  (`config/attribution.js`) to match the HERMES→HDX swap and the new
  basin levels — the HydroBASINS entry now says "levels 8 and 9"
  instead of just "level 8", and the Nepal-boundary entry now describes
  the OCHA/HDX COD-AB source (CC BY-IGO, commercial-use-safe) and its
  dual role (basin support-status refinement *and* district-based AOI
  selection) instead of the removed HERMES source.
- Frontend: **risk-surface visibility toggle + selectable color scheme**,
  scoped deliberately to the map raster and its own legend only — a
  design decision made explicit up front, not discovered mid-build:
  hazard-class swatches elsewhere (`ReportPanel.jsx`'s zonal table,
  `CriterionSnapshot.jsx`'s per-criterion thumbnails) keep using
  `riskValueToRgb`'s unchanged default scheme, since those are a
  discrete 1-5 class display, a different visual job than a continuous
  field, and changing them too was explicitly ruled out.
  - `lib/colorRamp.js`'s single hardcoded `RISK_STOPS` became a
    `RISK_SCHEMES` map of three named ramps, each keyed by an id: `risk`
    (the original green→yellow→red, unchanged), `viridis` (colorblind-
    safe, perceptually-uniform, monotonic lightness — the standard
    choice for continuous scientific/geospatial data), and `diverging`
    (ColorBrewer RdBu — blue↔red poles with a near-white neutral
    midpoint, the standard alternative convention for risk/hazard maps).
    `riskValueToRgb`/`riskValueToCssColor` both gained an optional
    `scheme` parameter defaulting to `risk`, so every existing caller
    that doesn't pass one is unaffected; `RISK_LEGEND_STOPS` (a static
    export) became `riskLegendStops(scheme)` (a function), its one
    consumer (`ResultPanel.jsx`) updated to call it with the live
    `state.riskColorScheme`. Candidate `viridis`/`diverging` stops were
    checked against the dataviz skill's `validate_palette.js` — its
    categorical-only checks (lightness band, chroma floor) don't apply
    to a continuous ramp per the tool's own footer note, but the checks
    that do (CVD separation, normal-vision floor on adjacent stops) both
    passed for both candidates.
  - `AppStateContext.jsx` gained `riskSurfaceVisible` (default `true`)
    and `riskColorScheme` (default `'risk'`) — both live outside
    `overlay`/`report` and are deliberately **not** reset on a new
    compute (`OVERLAY_LOADING`), unlike those two: a user who picks the
    colorblind-safe scheme almost certainly wants it to stick across
    their next AOI/compute too, not silently revert.
  - `MapView.jsx`'s risk-surface effect now re-runs on a color-scheme
    change too, not just a new result — but caches the GeoTIFF's raw
    bytes (keyed by `data_url`) in a ref so switching schemes re-decodes
    and re-colors the already-downloaded raster rather than re-fetching
    it. Visibility is a separate, cheap effect that just flips the
    already-rendered MapLibre layer's `visibility` layout property (the
    same mechanism the basin/district layer-visibility fix above uses),
    so toggling it never touches the network or re-decodes anything.
  - `ResultPanel.jsx` gained a "Show risk surface on map" checkbox and a
    color-scheme `<select>`, both above the legend, which itself now
    reads `riskLegendStops(state.riskColorScheme)` — the map raster and
    its own legend can never show two different schemes at once, since
    both read the same state.
  - Verified via a clean `vite build` and a headless-browser reload with
    zero console errors; not yet exercised through an actual interactive
    click-through (same tooling gap noted in the basin/district entry
    above).
- Frontend: **removed "Kathmandu Valley" branding**, at the user's
  explicit request now that basin/district selection covers all of
  Nepal, not just the original pilot area. Changed: the landing page's
  hero description and footer tagline (`LandingPage.jsx`), the sidebar
  header's brand subtitle (`Sidebar.jsx`, "Kathmandu Valley" → "Nepal"),
  and `index.html`'s `<meta name="description">` (also user-visible, in
  browser tab previews/search results/social shares — caught by a
  headless-browser DOM dump, not just a source-code grep). Deliberately
  **left unchanged**: the handful of mentions describing where specific
  *literature-sourced default values* actually came from
  (`LiteratureModal.jsx`, `ResultPanel.jsx`'s placeholder-breaks warning,
  `config/literature.js`'s Das (2019) AHP citation) — those are factual
  calibration provenance, not tool-scope branding, and matter *more* now
  that the tool spans all of Nepal: a user applying Kathmandu-Valley-
  calibrated elevation breaks to, say, the Terai plains should know
  those thresholds weren't derived for that terrain. Verified via a
  headless-browser DOM dump of the rendered landing page (not just a
  source grep, since the meta-description-tag case wouldn't have been
  caught by grepping only `.jsx`/`.js` files) confirming zero remaining
  "Kathmandu Valley" text outside the deliberately-kept calibration
  caveats.
- Frontend: **the vulnerability report moved out of the sidebar into a
  toggleable infographic overlay covering the map**, at the user's
  explicit request ("the sidebar is too crowded"), plus a data-gap
  disclaimer toast and a "Select all" criteria button. Three separate
  pieces landed together:
  - **Report overlay.** `ReportPanel.jsx` (the sidebar's own step 5)
    shrank to just the Generate/Regenerate button and a Show/Hide
    toggle; every heavy piece it used to render directly — headline stat
    tiles, the zonal table, the weighting breakdown, per-criterion
    snapshots, downloads — moved into a new `ReportOverlay.jsx`,
    absolutely positioned over `.map-area` (a new wrapper introduced
    around `MapView` specifically for this, since `MapView`'s own root
    div is fully MapLibre-managed and can't host React children
    directly — see `App.jsx`/`index.css`). New state:
    `reportOverlayVisible` (auto-`true` on `REPORT_LOADED` so a freshly
    generated report is immediately visible; reset `false` on
    `OVERLAY_LOADING`, the same trigger `report` itself already reset
    on) and a `TOGGLE_REPORT_OVERLAY` action. The "great infographic"
    part: a new population-by-hazard-class horizontal bar chart
    (`HazardPopulationChart`, plain HTML/CSS, no charting library) sits
    above the existing zonal table — one measure (population, the most
    vulnerability-relevant of the three the table already carries), not
    a second/third bar series on the same axis, per the "never a
    dual-axis chart" rule; each bar is directly labeled (class name +
    value) using the same swatch color the zonal table's own rows
    already use, so no separate legend box is needed. Candidate design
    checked against the dataviz skill's mark-spec guidance (thin bars,
    4px rounded data-end, 2px-ish row gaps).
  - **Data-gap disclaimer toast.** New `DataGapNotice.jsx`, floating
    over the map (not added to the sidebar, for the same
    crowding-avoidance reason as the report split), shown the moment
    `hand` or `soil_infiltration` is checked — both have a real,
    previously-documented coverage-gap issue (§3.6: HAND's edge/internal-
    pit nodata, measured ~12% on a real AOI; SoilGrids' small-AOI
    coverage gaps). New `config/criteria.js` exports:
    `DATA_GAP_DISCLAIMERS` (the exact message per criterion, citing the
    measured figures, not generic boilerplate) and `DATA_GAP_CRITERIA`
    (its keys). New state: `dataGapNotice` (`null`, or an array of
    criterion ids to show messages for at once), set by `TOGGLE_CRITERION`
    on a check-on transition for either id, or unconditionally to both
    ids by `SELECT_ALL_CRITERIA` (select-all always includes both, so
    always reminding of both together is simpler and more honest than
    only showing whichever wasn't already checked); cleared by a new
    `DISMISS_DATA_GAP_NOTICE` action, dispatched by the toast itself
    either after a 9s auto-dismiss timer or a manual close click.
  - **"Select all" criteria button.** New `SELECT_ALL_CRITERIA` reducer
    case in `CriteriaPanel.jsx`, mirroring `TOGGLE_CRITERION`'s own
    resync logic (AHP within-cluster matrices, manual weights,
    classification entries) but for every criterion at once in a single
    state transition, rather than looping individual dispatches.
  - A real bug was caught and fixed during this same pass, live: moving
    `MapView` under a new `.map-area` wrapper required re-pointing
    `.app-layout`'s flex-sizing from `.map-view` (now absolutely
    positioned, filling its wrapper) to `.map-area` itself, including the
    720px mobile breakpoint's own rule — missed on the first pass and
    caught by checking the built CSS, not assumed correct.
  - Verified live end to end via real scripted browser interaction (a
    CDP driver script, `Input.dispatchMouseEvent` to genuinely draw an
    AOI by dragging on the map canvas, real `.click()`s through the
    actual React event system, not just a static DOM dump) — filling a
    real gap the previous two entries had flagged ("no interactive
    click-through was run"). Confirmed: drawing an AOI, checking
    Elevation+Slope, computing (real DEM fetch, ~1.5s for a small AOI),
    generating a report (~7.5s including building classification),
    the overlay auto-appearing with real figures (39,087 buildings
    classified, a real 5-row population chart), the close button hiding
    it, and the sidebar's "Show report" button reopening the same
    result without regenerating. Select-all and the data-gap toast were
    also verified this way — worth noting for future test-authoring in
    this project: a `.click()` dispatched via a fresh CDP `Runtime.evaluate`
    connection can appear to have no effect if checked in the same
    script (there's a real async gap before React's state update
    reaches the DOM across a fresh CDP connection) — checking again via
    a *separate* subsequent call after a short delay is what actually
    confirmed correctness; this cost real debugging time before being
    understood as a harness artifact, not an app bug, and is recorded
    here so a future session doesn't re-diagnose it from scratch.
- Backend: **11th and 12th criterion sources, `rainfall` and
  `precipitation_chirps`** — two genuinely independent precipitation
  estimates, both registered rather than one replacing the other, since
  they fail differently and a user should be able to reason about each.
  - `rainfall` (`app/data/rainfall.py`) was contributed externally (a
    collaborator's branch, reviewed and merged after independent
    verification — its own test suite re-run in an isolated worktree,
    353/353 passing, plus a live functional call — rather than merged
    on trust): interpolates Nepal's DHM (Department of Hydrology and
    Meteorology) rain-gauge network — 254 quality-controlled stations,
    1980-2022, committed directly as a 22KB CSV resource (unlike every
    multi-GB raw source elsewhere in this project, gitignored) — via
    Inverse Distance Weighting over the K nearest gauges nationwide
    (never scoped to gauges strictly inside the AOI, since the network
    is sparse enough that would return empty for most real requests).
    The represented ETCCDI index is env-configurable
    (`RAINFALL_VARIABLE`: Rx1day default, or Rx5day/PRCPTOT/R95pTOT/
    SDII) — Rx1day (mean annual max 1-day rainfall) matches this
    project's own reference method (Parajuli et al. 2023, "the Siraha
    paper" — its full citation was already buried in a test docstring
    and surfaced properly into `attribution.py`'s new
    `METHODOLOGY_CITATIONS` by this same contribution, correcting a
    stale "no citation available" note in SPEC.md/HANDOFF.md).
    IDW is elevation-blind in a strongly orographic country; this is
    reported as a `source_warnings` entry (the same mechanism
    `twi`/`drainage_density`/`hand` use for their own caveats) whenever
    the contributing gauges span a wide elevation range or the nearest
    one is far away, never silently absorbed.
  - `precipitation_chirps` (`app/data/chirps.py`) is the satellite
    complement: CHIRPS-2.0's own 44-year (1981-2024) mean-annual-
    precipitation climatology, one public-domain global GeoTIFF
    (`data.chc.ucsb.edu`, verified live — no authentication, unlike GPM
    IMERG, evaluated and rejected for the same Earthdata-Login-required
    reason HYSOGs250m already was) — dense and gapless regardless of
    how close the nearest DHM gauge is, at the cost of satellite IR's
    own known bias over high, complex, snow-covered terrain, which IDW
    doesn't share. CRS is plain EPSG:4326 (no Homolosine-style
    reprojection-before-windowing needed, unlike `soil_infiltration`'s
    SoilGrids source); nodata (-9999.0) is supplied explicitly rather
    than read off the file, since the file's own GDAL metadata doesn't
    declare a NoData tag (confirmed live by sampling an open-ocean
    window). **A real bug caught live during implementation**: a small
    (~2km) real test AOI against CHIRPS's own coarse ~5.5km (0.05°)
    native pixels produced a raw `from_bounds` window of width=0.4,
    height=0.4 source pixels — `ds.read()` rejected that outright
    ("Invalid dataset dimensions: 0 x 0") rather than rounding it to
    something usable, a failure mode none of this project's other
    windowed-read sources (DEM 30m, WorldCover 10m, SoilGrids 250m) are
    coarse enough to hit against this project's own typical AOI sizes.
    Fixed with `_whole_pixel_window` (expands outward to whole source
    pixels, floored at 1×1) used by both the local and cloud read paths;
    verified live end to end that the exact previously-crashing AOI now
    resolves correctly through the real registry
    (`resolve_criterion_raster`) and the real `POST /api/overlay/compute`
    endpoint. 9 new tests (local-hit reprojection, the undeclared-
    NoData-tag handling, cache reuse, cloud fallback, the shared GDAL
    retry-env usage, two dedicated regression tests for the whole-pixel-
    window fix at both the unit and `get_chirps_precipitation` level,
    plus a `@pytest.mark.slow` live-network test) — 362 backend tests
    passing total, zero regressions.
  - Frontend: `precipitation_chirps` added to `config/criteria.js`
    (Hydrological cluster, alongside `rainfall`), default
    reclassification breaks derived from real CHIRPS values sampled
    across Nepal's actual climate range during implementation (~670mm
    dry western hills to ~3340mm wet mid-hills — Jumla and Pokhara
    respectively), not guessed blindly.
- Frontend: **landing-page redesign — a scroll-driven "zoom" sequence**,
  at the user's request: hero (zoomed in immediately, no scroll needed),
  team (zoomed in to fill most of the screen, exactly three members),
  then data sources (zoomed in last).
  - New `lib/useScrollZoom.js`: an IntersectionObserver-driven reveal
    hook (not a continuous scroll-position scrub, and deliberately not
    CSS `animation-timeline: view()` scroll-driven animations, which
    are Chromium-only as of this writing) — a section's wrapped content
    starts at `scale(0.88)`/`opacity: 0` and transitions to
    `scale(1)`/`opacity: 1` once substantially inside the viewport,
    reversing if scrolled back out (a live relationship with scroll
    position, not a one-shot animation — verified live both directions).
    The hero gets its "zoomed" state with zero special-casing: the
    observer's first callback fires immediately on `observe()` with
    whatever the current intersection state already is, and the hero is
    in the viewport the instant the page loads. Respects
    `prefers-reduced-motion: reduce` two ways — the hook skips the
    observer and jumps straight to the visible end state, and a
    belt-and-suspenders CSS media query forces full visibility
    regardless of class/timing, so a reduced-motion viewer is never left
    looking at suppressed (scaled-down/transparent) content. Verified
    live via emulated media (`Emulation.setEmulatedMedia`): the team
    section, never scrolled to, came back fully visible
    (`transform: none`, `opacity: 1`, `transitionDuration: 0s`).
  - `LandingPage.jsx`'s team and data-sources sections are new, bespoke
    markup (`team-showcase`/`source-showcase` in `index.css`) reading
    the same `config/attribution.js` data the existing `CreditsSection`
    component already did — deliberately NOT built on top of
    `CreditsSection` itself, since that component's compact, all-in-one
    grid (shared with `AboutModal`'s in-tool popup) is the right shape
    for a modal, not for a page section meant to "fill most of the
    screen": the team section is a fixed 3-column layout (exactly 3
    members, meant to read as one deliberate row, not a directory
    listing) with noticeably larger photos/cards than the old compact
    credit-card treatment. `AboutModal`/`CreditsSection` are unchanged
    and unaffected by this restructuring.
  - **A real, pre-existing data gap closed alongside this** (the actual
    ask behind "update the data sources section too"): `config/
    attribution.js`'s `SOURCE_ATTRIBUTIONS` only ever mirrored DEM/
    WorldCover/OSM, even after `ndvi`, `population_density`,
    `soil_infiltration`, `rainfall`, and `precipitation_chirps` were
    each added as registered criterion sources with their own backend
    `attribution.py` constants (§3.6) — all five were missing from both
    the landing page *and* the in-tool About modal entirely, silently,
    since nothing ever re-synced the two files. Fixed by mirroring all
    5 additional constants verbatim (this file's own established
    convention — no automated link to the backend constants, so this is
    a manual sync, flagged the same way the file's own header comment
    already flags the DEM/WorldCover/OSM entries). Total credited data
    sources: 8 (was 3) + the existing 2 basin/boundary infra credits =
    10. Verified live that both surfaces picked up all 10 automatically
    (`AboutModal` reads the identical `SOURCE_ATTRIBUTIONS` array, so
    this fix benefits it for free, not just the landing page).
  - Verified live end to end: hero zoomed on load with no scroll: team
    section zooms in and hero zooms out on scrolling to it; sources
    section zooms in and team zooms out on scrolling further; scrolling
    back to the top correctly re-triggers both sections back to their
    scaled-down/transparent starting state, confirming the reveal is
    genuinely bidirectional, not a one-shot "seen once, stays" reveal.
- Frontend: **hero section enlarged, plus an animated scroll-down cue**,
  at the user's feedback that the hero read as a small centered block
  in mostly-empty space rather than a screen-filling opener. Two real
  fixes, not just bigger numbers: `--text-display` (the hero title's
  only consumer) went from `clamp(2.4rem, 5vw, 3.8rem)` to
  `clamp(3.2rem, 7.5vw, 6rem)`, and — the actual fix, since bigger type
  alone barely changed how much of the 100vh section visually filled —
  `.hero--centered` gained its own `min-height: 82vh` so the block
  itself (and its radial-gradient glow background, sized to that same
  box) occupies most of the section, rather than staying a
  content-sized island vertically centered inside a mostly-bare 100vh
  area. Verified live via a properly-settled screenshot (an initial
  screenshot attempt caught the CSS transition mid-fade — real content,
  just not yet fully opaque — resolved by waiting for the transition to
  finish before capturing, not by changing anything about the reveal
  itself).
  - New `.hero__scroll-cue`: 3 chevrons cascading through
    opacity 0→1→0 on a staggered delay (0s/0.2s/0.4s), reading as a wave
    rippling downward — pinned to `.zoom-section--hero`'s own bottom
    edge via a new `overlay` prop on `ZoomSection` (renders as a sibling
    of the scaled/faded `.zoom-section__inner`, so the cue itself never
    scales/fades with the reveal — it should just always be there while
    the hero is on screen). Respects `prefers-reduced-motion` the same
    way the section reveals do: animation off, chevrons static at 0.5
    opacity rather than disappearing — verified live via emulated media
    (`animationName: "none"`, `opacity: "0.5"`). Verified live that the
    non-reduced-motion animation is genuinely cycling, not stuck: sampled
    computed opacity across all 3 chevrons at 400ms intervals and
    confirmed staggered peaks moving between chevrons over time, not all
    three frozen at one value.
- Frontend: **three hero polish fixes from user feedback on a
  screenshot**, one of which uncovered a real layout bug, not just a
  cosmetic tweak.
  - **The glow gradient looked like it was cut off by a rectangle.**
    Root cause: the radial-gradient background lived on `.hero--
    centered` (a box narrower and shorter than the full section,
    `max-width: 54rem` / `min-height: 82vh`) — CSS backgrounds never
    paint past their own element's box, so the gradient's "fade to
    transparent" was cut short by that box's own edges, reading as a
    visible rectangular silhouette rather than an organic falloff.
    Fixed by moving the gradient to `.zoom-section--hero` itself (the
    full-viewport-width/height section), which has genuine room to fade
    out before reaching any edge.
  - **Removed the hairline border between sections** (`border-top: 1px
    solid var(--color-border)` on the shared `.zoom-section` rule) — a
    thin but visible line at each section boundary that read as a stray
    rule cutting across the page between full-screen "scenes"; the zoom
    reveal itself is the transition cue, no divider needed.
  - **Moved `.hero__scroll-cue` up** (`bottom: var(--space-8)` →
    `var(--space-10)`) — and while verifying the new position live,
    found a real bug the request's screenshot hadn't shown: `.zoom-
    section`'s own `padding: var(--space-10) var(--space-8)` was
    stacking on top of `.hero--centered`'s own `min-height: 82vh` +
    padding, pushing the hero section's actual rendered height past
    100vh on shorter viewports — which pushed the bottom-anchored cue
    below the fold entirely (measured live: -24px past the viewport's
    own bottom edge, i.e. genuinely not visible, not just "a bit low").
    A second, related bug surfaced investigating this: `.landing__nav`
    sat in normal document flow *above* the hero, so even after fixing
    the padding stack, the hero's own `min-height: 100vh` box started
    below the nav rather than at the true top of the viewport, pushing
    everything (including the cue) down by the nav's own height. Fixed
    both: `.zoom-section--hero` now has `padding: 0` (the content block
    already owns its internal spacing), and `.landing__nav` is
    `position: absolute` overlaying the hero (its own dark background +
    glow work fine underneath the nav) rather than pushing it down —
    `.landing` gained `position: relative` as the nav's containing
    block. Verified live: hero section's own top now measures `0` and
    height exactly matches `window.innerHeight`; the cue's distance from
    the viewport's bottom edge went from `-24px` (cut off) to `+64px`
    (matching `--space-10` exactly, safely on-screen).
  - A screenshot-based verification pitfall from earlier in this same
    UI work recurred and was worth a permanent tooling fix rather than
    working around it again: single-shot headless screenshots can catch
    a CSS transition mid-flight or a scroll position mid-programmatic-
    scroll, so verification here used a small persistent-tab screenshot
    helper (waits for transitions to settle, screenshots the *same*
    already-scrolled tab rather than a fresh navigation) instead of
    re-deriving one-off scripts each time.
- **METEOR Project Nepal flood hazard maps**, investigated after the user
  linked `https://maps.meteor-project.org/map/flood-npl/` and asked
  whether it could be used in this project — added as both a live
  reference overlay and a new criterion source (§3.6), per explicit
  request ("both, do it").
  - **Licensing was investigated twice.** The first pass, based on a
    WebFetch summary of `meteor-project.org/data/`, wrongly reported the
    flood hazard maps as possibly CC BY-NC-SA 4.0 (non-commercial-only).
    Told explicitly to "be completely sure about it," the second pass
    fetched the flood map's own page HTML directly via `curl` (bypassing
    the summarizer) and found the CC BY-NC-SA 4.0 text actually belongs
    to a *different* METEOR product — "Exposure Data" (building-count
    CSVs, "Copyright (C) 2020 ImageCat Inc. and METEOR Project
    Consortium") — not the flood hazard layers. The flood map's own page
    states its license twice, unambiguously: `<li>Map licensed under
    <strong><a href="...odbl/index.html">ODbL</a></strong></li>` and a
    dedicated `<h5>License</h5>` section naming the Open Data Commons
    Open Database License. ODbL is the same license OpenStreetMap itself
    uses in this project (`OSM_ATTRIBUTION`) — commercial use and
    redistribution both permitted, with attribution — so both the
    overlay and the criterion are legitimately usable here.
  - **Data format**, confirmed live by downloading METEOR's own
    QGIS-project package (`.../map/flood-npl/download`, 335,192,259
    bytes, no HTTP Range support — confirmed by sending a `Range:`
    header and getting back a plain 200 with no `Accept-Ranges`, so no
    partial-download shortcut exists) and inspecting the extracted
    `metadata.txt` and one real layer (`layers/FD_1in100.tif`) via
    rasterio: 30 GeoTIFFs total (3 flood types — Fluvial Defended `FD`,
    Fluvial Undefended `FU`, Pluvial `P` — × 10 return periods each,
    5/10/20/50/75/100/200/250/500/1000 years), CRS EPSG:4326, dtype
    float32, ~90m (3 arcsecond) native resolution, values are modeled
    water depth in meters (metadata.txt: "the maximum water depth that
    would be expected if a flood event of the specified return period
    were occurring"). Two sentinel values found by direct pixel
    inspection, neither declared as a GDAL NoData tag: -9999.0 (97.2% of
    `FD_1in100.tif`'s pixels — outside the Fathom model's simulated
    floodplain domain entirely, e.g. hillslope/ridge terrain, not a
    data-quality gap) and 999.0 (0.018% — a much rarer masked value).
    Produced by the Fathom global flood hazard framework (2D shallow
    water equations over the MERIT global DEM/hydrography) — the WMS/
    WMTS/TMS/WFS tile endpoints (MapProxy) were confirmed live and
    unauthenticated, and a real WMTS tile fetch at z=12/x=3018/y=1719
    was visually confirmed to show genuine flood-extent geometry
    tracing real river network structure near Kathmandu, not a
    placeholder or broken image.
  - **Live reference overlay** (`frontend/src/components/MapView.jsx`):
    a new `MeteorFloodControl` (mirrors `BasemapControl`'s exact
    onAdd/onRemove/dispatch shape) with a flood-type select, a
    return-period select, and a visibility toggle, added top-left beside
    the basemap control. Reads METEOR's live WMTS tile service directly
    (`.../mapproxy/npl-flood/wmts/{type}-{years}/webmercator/{z}/{x}/{y}.png`)
    — pre-styled RGB PNG, fine for a visual reference layer, off by
    default, 0.7 opacity, drawn above the basemap but below the app's
    own interactive layers (same bottom-insertion reasoning as the
    basemap layer). New state: `meteorFloodVisible`/`meteorFloodType`/
    `meteorFloodReturnPeriod` (`AppStateContext.jsx`), defaulting to
    `fd`/100 to match the criterion's own default. Deliberately a
    *separate* thing from the criterion below — this overlay always
    reads METEOR's live service regardless of what's downloaded locally;
    the criterion cannot use that service at all (next point).
  - **New criterion source** `flood_hazard_meteor`
    (`backend/app/data/meteor_flood.py`, registered in
    `overlay/sources.py`) — **local-only, with no cloud fallback**,
    unlike every other local-check-first module in this package: WMS/
    WMTS only serve pre-styled PNG tiles (colorized RGB, not numeric
    depth values), so there is no live windowed-read endpoint this
    module could fall back to. A missing local file therefore raises
    `DataSourceUnavailableError` with a direct download link, rather
    than silently degrading. Defaults to `FD`/`1in100`
    (`config.METEOR_FLOOD_TYPE`/`METEOR_FLOOD_RETURN_PERIOD`, env-
    overridable, filename convention matches the zip's own
    `layers/{TYPE}_{RETURN}.tif`) — "defended" reflects expected
    flooding given Nepal's real flood-defence infrastructure, and
    1-in-100 is the standard regulatory/planning benchmark return
    period. Both sentinel nodata values are masked to NaN before
    reprojection (`_mask_sentinels`); reuses chirps.py's
    `_whole_pixel_window` fix (a small AOI against a coarse native pixel
    size can produce a degenerate fractional read window) since
    METEOR's ~90m pixels are coarser than DEM/WorldCover/SoilGrids.
    Carries a genuinely new *kind* of caveat versus `twi`/
    `drainage_density`/`hand`'s AOI-edge reliability warnings: below 10%
    in-domain pixel coverage, `.warning` explains that most of Nepal is
    legitimately outside the Fathom model's simulated floodplain domain
    (not a data gap) — live-verified against the real downloaded
    `FD_1in100.tif` with two real AOIs: a Kathmandu Valley floodplain
    bbox came back 15.3% valid (mean depth 1.65m, no warning), and a
    Shivapuri hillslope bbox north of Kathmandu came back 0.0% valid
    (warning present). Also flagged in `config/criteria.js`'s
    `DATA_GAP_DISCLAIMERS` (same transient-toast mechanism as `hand`/
    `soil_infiltration`), since METEOR/Fathom's own documentation
    explicitly recommends its output for regional guidance, not detailed
    local-scale assessment — the same caveat class those two criteria's
    disclaimers already exist for.
  - Full citation (`attribution.py`'s `METEOR_FLOOD_ATTRIBUTION`,
    mirrored in `frontend/src/config/attribution.js`): Sampson, Smith,
    and both Yamazaki et al. papers metadata.txt cites by author/year/
    DOI only — full titles confirmed separately by DOI lookup during
    implementation, not invented, and added to `literature.js`'s
    `REFERENCES` (`sampson2015`/`smith2015`/`yamazaki2017`/
    `yamazaki2019`/`meteorproject`) for the criterion's own info-button
    entry.
  - 8 new backend tests (`tests/data/test_meteor_flood.py`, mirroring
    `test_chirps.py`'s structure with the cloud-fallback tests swapped
    for a hard-failure test): local-hit, missing-file failure, both
    sentinels masked correctly, processed-cache reuse, the low-coverage
    warning, type/return-period file selection, and the two
    `_whole_pixel_window` regression tests. Full suite (370 tests,
    excluding the `slow`-marked live-network ones) still green in the
    real backend container after this addition.
  - **Follow-up, reported by the user**: "toggling it on and off
    doesn't work" — a real bug in the overlay's own WMTS URL, not the
    toggle wiring itself (confirmed live in a headless-Chrome CDP
    session: the layer/source were created correctly and their
    `visibility` layout property genuinely did flip on click, but every
    tile request 400'd). Root cause: `meteorFloodTiles`'s layer id was
    built as `{type}-{years}` (e.g. `fd-100`), but the real WMTS layer
    identifiers are `{type}-1in{years}` (e.g. `fd-1in100`) — confirmed
    authoritatively against the live WMTS `GetCapabilities` XML's own
    `ows:Identifier` entries, and by a direct tile fetch: `fd-100` → 400,
    `fd-1in100` → 200. Also added the **legend the user asked for**:
    `MeteorFloodLegend.jsx`, a plain React component (not a MapLibre
    IControl, since — unlike `MeteorFloodControl` — it has no
    interactive elements, just state-driven visibility) rendered as a
    `.map-area` sibling of `MapView` exactly like `DataGapNotice`, shown
    bottom-right whenever `meteorFloodVisible` is true. Rather than
    hand-drawing swatches, it embeds METEOR's own real `GetLegendGraphic`
    (WMS) output live, so it can never drift from whatever styling the
    overlay tiles actually use — confirmed by direct request during
    implementation (a real 102×198 PNG: color swatches for 0.1/1/2/3/4/5m
    depth bins plus "Permanent" water). One more real bug here: the WMS
    `GetCapabilities`'s own advertised `LegendURL` points at an internal
    hostname (`https://gem/mapproxy/...`) that isn't publicly
    resolvable — `meteorLegendUrl()` rebuilds the same query string
    against the public host (`maps.meteor-project.org`) MapView.jsx's
    WMTS tiles already use, confirmed live (`imgNaturalWidth: 102`, i.e.
    the real image, not a broken-image placeholder). Both fixes verified
    live in a headless-Chrome CDP session: layer-id fix confirmed via
    `map.getLayoutProperty` flipping correctly; legend confirmed via
    fresh load → legend absent → click toggle → legend present with the
    correct title/image → click again → legend gone.
  - **Second follow-up, reported by the user**: "the meteor flood map
    doesn't show up." The verification above was real but incomplete —
    it confirmed the layer/source existed and `visibility` flipped
    correctly, and separately that the *legend* image loaded, but never
    actually confirmed the overlay *tiles themselves* rendered on
    screen, which is what the user meant by "doesn't show up." A wider
    root cause than the layer-id bug: METEOR's tile server sends **no
    `Access-Control-Allow-Origin` header at all** (confirmed live via
    `curl -I`) and MapLibre GL sets `crossOrigin` on its raster tile
    requests (needed to read pixel bytes into a WebGL texture — unlike
    the legend's own plain `<img src>`, which has no `crossOrigin` and
    was genuinely unaffected, which is exactly why it kept looking fine
    through every earlier check). Every tile request therefore failed as
    a browser-enforced CORS error — confirmed live via a fresh
    headless-Chrome CDP session showing repeated "TypeError: Failed to
    fetch" from inside maplibre-gl's own tile-loading code, for a URL
    that succeeded via a server-side `curl` moments earlier (the
    session's first pass had dismissed this exact error as unrelated
    sandbox noise — it wasn't). Fixed by adding a same-origin proxy
    route, since browsers don't apply CORS to server-to-server requests:
    `GET /api/overlay/meteor_flood_tile/{flood_type}/{return_period}/{z}/{x}/{y}.png`
    (`app/overlay/meteor_tile_proxy.py`, `fetch_meteor_flood_tile`,
    registered in `router.py`) fetches the real tile from METEOR via
    `httpx` and returns it from this app's own backend origin, which the
    frontend already trusts (`app/main.py`'s `CORSMiddleware`).
    `flood_type`/`return_period` are validated against the real 30-entry
    catalog before being interpolated into the upstream URL — load-
    bearing, since this is a public, unauthenticated route (an
    unvalidated value would make it an open proxy for arbitrary paths
    under `maps.meteor-project.org`). Upstream failures are split by
    kind: a 4xx from METEOR (a z/x/y outside its own tile matrix — a
    routine condition at the edges of any raster layer's zoom/coverage
    range, not a bug) raises `MeteorTileNotFoundError` → 404; a 5xx or a
    network failure raises `DataSourceUnavailableError` → 503, so
    routine boundary tiles never get logged/surfaced as if the whole
    service were down. `MapView.jsx`'s `meteorFloodTiles()` now points
    at this proxy instead of `maps.meteor-project.org` directly; the
    legend's `<img>` is untouched (it never needed a proxy). 51 new
    backend tests (46 in `tests/overlay/test_meteor_tile_proxy.py` —
    the allow-list, both error-kind splits, network-failure handling,
    and a full 3×10 parametrization over the real catalog; 5 more
    router-level request/response-wiring tests appended to
    `test_router.py`), full suite (421 tests) green. Verified end-to-end in a fresh headless-Chrome CDP
    session, jumped to a known Kathmandu-Valley floodplain bbox: real
    flood-hazard geometry rendered on screen, tracing actual river
    channels, colored to match the legend exactly, with zero console
    fetch errors (down from dozens per interaction before the fix).
- Frontend: new landing-page section, **"How it works"** — inserted
  between the hero and the team section (`LandingPage.jsx`'s
  `#how-it-works` `ZoomSection`, same scroll-zoom-reveal mechanism as
  every other landing section), at explicit request: "how to use, what
  is ahp, methods to follow, using meteors as a criteria vs validation
  ... before the teams and credits." A 2×2 card grid
  (`.method-showcase`, a new class — deliberately a FIXED
  `repeat(2, ...)`, not `source-showcase`'s own `auto-fit`, which fit 3
  unevenly-sized cards per row at ordinary desktop widths here and read
  as unbalanced; `align-items: start` keeps each card sized to its own
  content instead of stretching to its row's tallest neighbor):
  - **How to use** — a numbered 5-step list (new
    `.method-showcase__steps`, CSS-counter badges reusing
    `--color-primary-soft`/`--color-primary`, the same accent
    `team-showcase__avatar` already uses) mirroring the in-tool
    sidebar's own 5 steps exactly: Area of interest, Criteria,
    Weighting, Compute, Vulnerability report.
  - **What is AHP?** — reuses `config/literature.js`'s
    `METHOD_INTRO.body[0]` verbatim (imported, not re-written), the
    same "one place holds the real text" discipline
    `config/attribution.js`'s own `SOURCE_ATTRIBUTIONS` comment already
    documents for its own verbatim-backend-string copy — keeps the
    landing page and the in-tool `LiteratureModal` from ever drifting
    apart on the same explanation.
  - **The method** — the 5 canonical clusters (Topographic,
    Hydrological, Land Use, Infrastructure, Exposure) and the Parajuli
    et al. (2023) reference-method citation, both already established
    facts (`config/criteria.js`'s `CANONICAL_CLUSTERS`,
    `attribution.py`'s `METHODOLOGY_CITATIONS`), not new claims.
  - **METEOR: criterion vs. validation** — the distinction from this
    same session's earlier discussion, written out plainly for a first-
    time visitor: as a *criterion* (`flood_hazard_meteor`), METEOR's
    modeled depth is one weighted input blended into the composite AHP
    score; as *validation* (the live WMTS reference overlay), the same
    organization's data is shown independently on the map and never
    blended into the score, specifically so a user can sanity-check
    their own result against a third party's model.

  Verified live in a fresh headless-Chrome CDP session: scrolled to
  `#how-it-works`, confirmed the section's own `--active` class and all
  4 card titles render, confirmed the full section order
  (hero → how-it-works → team → sources) matches what was asked for,
  and screenshotted the resulting layout both before and after the
  grid-balance fix above. Frontend build clean throughout.
- Backend: **`flood_hazard_meteor`'s nodata is now a real depth of
  0.0m, not exclusion** — at the user's explicit request: "only the
  meteor area gets flood hazard output, make it so that the nodata in
  meteor is 0 and all the aoi gets hazard classification." Two real bugs
  fixed together, both only visible once the first was addressed:
  - `_resolve_sentinels` (renamed from `_mask_sentinels`) no longer maps
    -9999.0 ("outside the Fathom model's simulated floodplain domain")
    to NaN/excluded — it resolves to a real depth of 0.0m instead. This
    is a scientifically defensible reinterpretation, not a literal
    "nodata equals zero" hack: metadata.txt's own documented semantics
    say those pixels are ones the model deliberately never attempts to
    flood, which for a *flood hazard* criterion genuinely does mean "no
    hazard here", not "unknown" — the same reasoning soil.py's own
    docstring already applies in the opposite direction (SoilGrids'
    nodata stays nodata specifically because no equivalent documented
    reason exists to remap it; METEOR's own documentation supplies
    exactly that reason). The rarer 999.0 sentinel (permanent water,
    ~0.02% of pixels) is deliberately NOT given the same treatment —
    mapping it to 0 would misclassify permanent water as the lowest-risk
    case, a real correctness bug the literal instruction doesn't
    actually ask for once its intent is followed through consistently.
    It resolves instead to `_PERMANENT_WATER_DEPTH_M` (5.0, this file's
    own observed maximum real depth), landing in the top risk_class
    alongside the worst real modeled cells. `reproject_to_grid` is now
    called with `src_nodata=None` (there is no remaining sentinel in the
    source array by the time it reaches reprojection); the low-in-domain-
    coverage `.warning` the first version attached is gone along with
    the gap it warned about, and `flood_hazard_meteor`'s
    `DATA_GAP_DISCLAIMERS` entry (config/criteria.js) was removed for
    the same reason.
  - **A second, independent bug**, caught live only because the first
    fix made it visible: even after -9999 became 0.0, a real AOI over
    the actual `FD_1in100.tif` still came back ~98.4% valid, not 100% —
    the mean depth was still being dragged to roughly -150m by a
    residual sliver of genuine `dst_nodata` pixels. Root cause:
    `_whole_pixel_window` cropped its read window tightly to the AOI's
    own bounds (rounded to whole pixels, no margin) — bilinear
    resampling needs real neighboring source data around each
    destination pixel, and a window with no margin starves the
    destination grid's own edge pixels of that neighbor data, leaving
    them at `dst_nodata` regardless of what the sentinels resolve to.
    This bug predates this whole fix and affects every other windowed-
    read source in this package the same unbuffered way (dem.py/
    chirps.py's own `_read_local_window` use plain `from_bounds` too),
    but was invisible for METEOR specifically until now: previously
    -9999 pixels were ALL treated as nodata regardless of cause, so a
    few extra edge-margin nodata pixels were undetectable against the
    ~97% domain-sentinel nodata already present — and METEOR's own
    ~90m native pixels make the fringe proportionally much wider than
    DEM (30m) or WorldCover (10m)'s. Fixed with a new
    `_WINDOW_MARGIN_PX` (tuned live against the real file: 1px of margin
    reached 99.9% valid on a real floodplain AOI, 2px reached the full
    100%). Live-verified against the real downloaded `FD_1in100.tif`
    over three real AOIs after both fixes: a Kathmandu floodplain bbox
    (100% valid, mean depth 0.25m), a Shivapuri hillslope bbox (100%
    valid, mean depth exactly 0.0m — entirely outside the model's
    domain, correctly resolved), and a small ~500m tight bbox (100%
    valid, mean 0.0m) — all three previously ranged from 0% to 15.3%
    valid. Confirmed end-to-end through the real `POST
    /api/overlay/compute` endpoint too (the Shivapuri hillslope AOI,
    previously entirely excluded, now computes a real risk surface with
    zero source_warnings). 4 tests replaced/added in
    `test_meteor_flood.py` (12 total now, up from 8): sentinel-resolution
    tests for both sentinels independently and mixed together, a direct
    unit test on `_whole_pixel_window`'s own margin math, and an
    end-to-end coverage test using a realistically-sized (not
    artificially generous) fixture. Full suite (425 tests) green.
- Backend: **real-flood validation** — `POST /api/overlay/validate` and
  `GET /api/overlay/validation-events`, at the user's request after a
  wider research thread into what real historical Nepal flood data
  exists (World Flood Programme/APFM, Dartmouth Flood Observatory,
  UNU-INWEH's World Flood Mapping Tool, Copernicus EMS) and where the
  session's own earlier conclusion landed: METEOR shouldn't be used as
  either a criterion or a validation reference, since comparing a
  computed risk surface against it only checks agreement between two
  *models*, not real-world accuracy — the correct method (already named
  in `config/literature.js`'s own `METHOD_INTRO`) is a success-rate
  curve / AUC against a real, observed flood inventory.
  - **Real event data acquired and verified live**, not assumed from
    metadata: UNOSAT's Sentinel-1 SAR flood extent for the September
    2024 Nepal floods (27 Sep 2024, Koshi & Madhesh Provinces),
    downloaded from HDX, license confirmed directly on that dataset's
    own metadata as CC BY-SA (not assumed from a generic platform
    footer, which said something different — the structured `license`
    field is the authoritative one). A real, live-verified discrepancy
    caught along the way: despite the HDX dataset's own title naming
    "the Capital city of Kathmandu," this file's actual geometry (bounds
    checked directly) never reaches Kathmandu Valley — all real detected
    flooding is in the Terai lowlands. Also pulled the Global Flood
    Database's real August-2017 South Asia flood raster directly from
    its public GCS bucket (`gs://gfd_v3`, no Earth Engine auth needed)
    as a second reference — confirmed real flooded pixels inside Nepal's
    own bbox, zero in Kathmandu Valley specifically, the same pattern.
    2019 was searched for but not found (UNOSAT's Nepal catalog starts
    2020; the Global Flood Database's own window ends Dec 2018; no
    Copernicus EMS activation exists for it).
  - `app/data/validation_extent.py` (new): local-only, no cloud fallback
    (same reasoning as basins.py/meteor_flood.py — each event is a
    one-time downloaded product, no live endpoint exists).
    `config.VALIDATION_EVENTS` registers events by key (currently one:
    `nepal_2024_terai`) so adding a future event (a genuine Kathmandu-
    covering product, or a 2017/2019 source if one is found) needs only
    a new dict entry, no code change. Rasterizes the real flood polygon
    onto the exact same `compute_aoi_grid` every criterion source uses
    (`all_touched=False`, the same area-coverage convention
    density_raster.py's own building-footprint rasterization already
    uses), so it always lines up pixel-for-pixel with a risk surface
    computed for the same AOI with no reprojection needed downstream.
  - `app/overlay/success_rate.py` (new): the actual success-rate curve /
    AUC math, a pure function taking the risk surface + observed mask.
    Verified against closed-form values, not just "does it run": a
    risk score that exactly equals the observed label gives AUC = 1 -
    p/2 (p = flooded fraction); the exact inverse gives p/2; a random
    ranking gives ~0.5 — all confirmed live before writing the pytest
    versions.
  - `app/overlay/validate.py` (new): thin orchestration — reuses
    `compute_overlay` directly (so validating an already-computed AOI/
    criteria/weights combination never recomputes the risk surface,
    confirmed live via a call-count check) rather than reimplementing
    any part of the compute pipeline.
  - Live end-to-end run against the real UNOSAT data and a real
    live-fetched Copernicus DEM criterion (not mocked) over a real
    30km×30km Terai AOI (chosen by grid-searching the actual flood
    polygon data for its densest cluster, 900 km², ~5.3% flooded — under
    the 1000 km² area cap): AUC 0.590, 9,006,295 valid pixels compared,
    480,304 observed-flooded — a modest-but-real result (elevation alone
    beats random only moderately in flat Terai terrain, which is
    itself an honest, expected finding, not a bug to chase). Confirmed
    identical over both a direct function call and the real HTTP
    endpoint (a temporary local uvicorn server, since Docker Desktop
    wasn't running this session).
  - 22 new tests (`test_success_rate.py`, `test_validation_extent.py`,
    `test_validate_router.py`) plus `VALIDATION_EVENTS`/
    `LOCAL_VALIDATION_EXTENTS_DIR` isolation added to both
    `tests/data/conftest.py` and `tests/overlay/conftest.py`'s own
    no-local-sources-by-default fixtures. Full suite (441 tests) green.
- Frontend: **sidebar step 6, "Validate"** (`ValidationPanel.jsx` +
  `SuccessRateChart.jsx`) -- an event picker + "Validate" button, gated
  on `state.overlay` being loaded exactly like `ReportPanel` (a follow-up
  check on an existing result, reusing its own `criteriaUsed`/
  `weightsUsed` snapshot rather than the live, possibly-since-changed
  criteria/weighting panels). New `validation`/`validationEvents`/
  `selectedValidationEvent` state slices, reset on `OVERLAY_LOADING`
  alongside `report` for the same reason. The chart itself (`dataviz`
  skill followed): plain inline SVG, no library, matching
  `ReportOverlay.jsx`'s own existing chart's dependency-free convention
  -- the real success-rate curve in `--color-primary`, a dashed muted
  "random ranking" reference diagonal (an annotation, not a second data
  series, so a direct label instead of a legend box), and a hover
  crosshair + tooltip.
  - Verified live end-to-end through the actual running app (headless-
    Chrome CDP, Docker back up after this session found and launched it
    — see the note on that below): drew a real AOI inside the 2024
    Terai flood cluster, computed a single-criterion (`dem_elevation`)
    risk surface, ran Validate, and got a real rendered result (AUC
    0.586, "poor", the curve plotted correctly above the diagonal,
    correct attribution) — screenshotted, not just DOM-text-checked.
  - **A genuinely important finding surfaced by this exact live run**,
    not a bug: the map showed the computed risk surface as one uniform
    solid-red block across the whole AOI. Root cause: `dem_elevation`'s
    default reclassification breaks (`config/criteria.js`) are
    calibrated to the Kathmandu Valley floor (~1300-1840m) — this
    Terai AOI sits at ~70-100m elevation, entirely below even the
    lowest break, so every pixel saturates to risk_class 5 uniformly.
    With zero variation in the risk score, there is nothing real to
    rank pixels by, and the AUC (0.586, barely above the 0.5 "random"
    floor) reflects exactly that — not a validation-feature bug, but a
    live, concrete demonstration of the exact caveat raised earlier in
    this same session's own discussion (Kathmandu-calibrated defaults
    are close to meaningless outside Kathmandu Valley; a real
    cross-region validation should use AOI-specific data-driven breaks
    from the existing `POST /criteria/breaks` endpoint instead of the
    static defaults).
  - Also **found Docker Desktop was not running** at the start of this
    phase (from earlier in this same session) and started it directly
    (`Docker Desktop.exe`, ~10s to a ready daemon, containers auto-
    resumed) rather than continuing to work around it — restored the
    ability to verify against the real containers (previous phase's
    verification used a temporary local `uvicorn` server instead).
- **Real observed flood-extent map overlay**, following on from the
  Validate step above: the same real flood-extent polygon POST
  /validate checks a risk surface against is now also directly
  visible on the map, toggleable, in the same UI slot/pattern as the
  METEOR reference overlay -- not just a number in a panel.
  - Backend: `GET /api/overlay/validation-events/{event}/extent.geojson`
    (`app/data/validation_extent.py`'s new `get_validation_extent_geojson`,
    `lru_cache`d since it has no AOI dependency) -- reads the same local
    shapefile `get_observed_flood_mask` uses for the actual validation
    math, reprojects to EPSG:4326, and `.simplify()`s to ~11m (matching
    the project's own 10m analysis grid) for display only. Hit a real
    bug here: the raw UNOSAT shapefile carries a `Sensor_Dat`
    datetime64 column that geopandas' `.to_json()` can't serialize --
    fixed by building a geometry-only GeoDataFrame before serializing.
    3 new route tests (404 unregistered event vs 503 registered-but-
    missing-file, matching the same distinction the rest of this
    router already makes elsewhere).
  - Frontend: `ValidationExtentControl` (`MapView.jsx`), a MapLibre
    IControl mirroring `MeteorFloodControl` exactly -- an event
    `<select>` + a show/hide toggle button, top-left. Its events list
    is fetched independently of the sidebar's own "Validate" step
    (`StepSection` doesn't mount a locked step's content at all, so
    `ValidationPanel`'s identical fetch effect wouldn't run until a
    risk surface already exists) -- both effects share one idle-status
    guard so whichever mounts first "wins," never a duplicate fetch.
  - **Two real bugs hit and fixed during live verification**, both the
    same underlying shape: MapLibre's `.once('load', cb)` is a
    one-time event subscription, safe as a "defer until style ready"
    fallback only when the thing gating it is synchronous. The
    visibility-toggle effect's `map.once('load', apply)` fallback
    assumed the layer would exist by the time 'load' fires, but this
    layer's creation is gated behind an independent async GeoJSON
    fetch that can resolve well after 'load' already fired (a
    one-time event doesn't replay for a listener added after the
    fact) -- threw "Cannot style non-existing layer." Fixed by
    dropping that fallback for this one effect in favor of a plain
    `if (!map.getLayer(...)) return` no-op guard (safe since the
    layer-creation effect already bakes in the correct current
    visibility at creation time). Separately, the layer-creation
    effect itself read `state.validationExtentVisible` from its own
    closure rather than `stateRef.current` -- a stale value if a
    toggle click landed between the effect starting and its fetch
    resolving; fixed to read `stateRef.current` the same way every
    other async-then-mutate-the-map effect in this file already does.
  - Verified live end-to-end (headless-Chrome CDP): launched the tool,
    confirmed the events list populates the control, toggled the
    overlay on, jumped the map to the Terai, and screenshotted a real
    render -- the magenta flood-extent polygons trace the Koshi
    river's channel and floodplain exactly as expected, not a
    solid/empty layer.
- **Validation metrics expanded**: precision, recall, F1, IoU, and PR-
  AUC, alongside the existing success-rate/AUC. Two families, scored
  differently on purpose:
  - **Threshold-free** (`app/overlay/success_rate.py`, extended, not a
    new module): PR-AUC and its own (recall, precision) curve, computed
    from the exact same descending-risk-score sweep the existing
    success-rate curve already builds -- recall at each cutoff IS that
    curve's own y-value, so the only new quantity is precision
    (captured flooding / pixels predicted positive at that cutoff).
    Its own uninformative baseline is `observed_flooded_fraction`, NOT
    0.5 -- documented prominently (module docstring, API field
    description, and the frontend's own hero-stat label) since silently
    reusing the AUC panel's 0.5 baseline language here would have been
    actively misleading.
  - **Threshold-based** (`app/overlay/confusion_metrics.py`, new
    module): precision/recall/F1/IoU at ONE fixed operating point --
    hazard classes 4 (High) + 5 (Very High) as "predicted flooded" --
    rather than an arbitrary top-k cutoff. That exact set
    (`HIGH_RISK_CLASSES`) already meant "high risk" everywhere else in
    this app (the map's own hazard-class legend, POST /report's
    `high_risk_building_count`/`high_risk_population`); moved from
    being a local constant inside `report.py` to living in
    `hazard_classes.py` instead (report.py now imports it from there)
    so every consumer shares one definition rather than two that could
    silently drift apart.
  - `POST /api/overlay/validate`'s response grew `pr_auc`,
    `precision_recall_curve`, `precision`, `recall`, `f1`, `iou`, and
    the four raw confusion-matrix pixel counts -- additive only, no
    existing field changed shape or meaning.
  - Frontend: a new `PrecisionRecallChart.jsx` (reuses
    `SuccessRateChart.jsx`'s own CSS classes -- visually the same chart
    language, a horizontal reference line at the base flooded rate
    instead of a diagonal) plus a 4-tile precision/recall/F1/IoU stat
    row in `ValidationPanel.jsx`, both below the existing AUC hero and
    success-rate curve.
  - 18 new backend tests (7 in `test_confusion_metrics.py` against
    hand-built confusion matrices with known answers, including a
    partial-overlap case computed by hand, not just the perfect/
    disjoint extremes; 4 new PR-AUC assertions in `test_success_rate.py`;
    router-level assertions added to the existing aligned/opposite
    `test_validate_router.py` cases). Full suite (459 tests) green.
  - **A real label-collision bug caught during live verification, not
    guessed at**: `PrecisionRecallChart`'s first draft copied
    `SuccessRateChart`'s own right-edge label placement for both the
    curve and its reference line -- but a precision-recall curve
    typically converges toward the reference's own height by the right
    edge (precision trends toward the base rate as recall approaches
    1), so "Model" and "Random" rendered on top of each other. Fixed by
    labeling the (constant-height) reference line at the LEFT edge
    instead, where the curve is at its opposite (recall=0, precision=1)
    extreme and never collides.
  - Verified live end-to-end (headless-Chrome CDP): drew a real AOI
    inside the same 2024 Terai flood cluster used for this session's
    earlier AUC verification, computed a single-criterion
    (`dem_elevation`) risk surface, ran Validate, and got a real,
    internally-consistent result -- recall 1.00, precision/IoU 0.02,
    F1 0.04 (exactly `2*0.02*1/(0.02+1)`), all following directly from
    the same already-documented finding that Kathmandu-calibrated
    default breaks saturate every Terai pixel to hazard class 5, so
    literally everything is "predicted flooded" -- not a new bug, a
    second live confirmation of the same known caveat, this time
    visible in the confusion-matrix metrics rather than just the AUC.
- **METEOR model-agreement comparison** (POST /api/overlay/compare-
  meteor + sidebar step 7 "Compare to METEOR") -- at explicit request,
  extending the validation feature to also compare against METEOR's own
  modeled flood hazard. Deliberately kept as its own endpoint/module/
  frontend step, sharing success_rate.py's and confusion_metrics.py's
  own comparison machinery (both already fully generic over what the
  "second mask" represents) but NEVER merged into POST /validate's own
  event list or exposed through "Validate" language anywhere -- this
  checks agreement between two independently-produced models, not
  real-world accuracy, exactly the distinction this session's own
  earlier discussion established (METEOR rejected as either a criterion-
  validation reference or ground truth). A model-agreement result must
  never read as if it were validation against real data.
  - Backend: new `app/overlay/meteor_comparison.py` --
    `compare_risk_surface_to_meteor` reuses `compute_overlay` +
    `app/data/meteor_flood.py`'s `get_meteor_flood_hazard` (the same
    local-only, single-configured-flood_type/return_period raw depth
    source already used as an optional AHP criterion) +
    `compute_success_rate_curve`/`compute_confusion_metrics`. METEOR's
    continuous depth is binarized via `depth_m > 0.0` -- the standard
    depth-nonzero convention for deriving a binary extent from a
    continuous depth grid, covering both a real modeled depth and the
    permanent-water sentinel (already resolved to 5.0m by
    meteor_flood.py's own docstring), excluding only the -9999 "outside
    the model's domain" sentinel (already resolved to exactly 0.0m).
  - `success_rate.py`'s and `confusion_metrics.py`'s own "zero positive
    pixels" error message gained an optional `zero_positive_hint`
    parameter (default preserves the exact original validate-specific
    wording, so `validate.py`'s call site and its existing tests needed
    no changes) -- without this, meteor_comparison.py's own AOI-outside-
    METEOR's-domain error would have misleadingly told the user to
    check `config.VALIDATION_EVENTS`, which has nothing to do with
    METEOR at all.
  - `POST /api/overlay/compare-meteor` mirrors `/validate`'s response
    shape (auc/curve/pr_auc/precision_recall_curve/precision/recall/f1/
    iou/pixel counts) but with `meteor_flooded_fraction`/
    `n_meteor_flooded_pixels` in place of the `observed_*` names, and
    `meteor_flood_type`/`meteor_return_period` instead of `event`/
    `event_label` -- no `event` field at all, since only one METEOR
    flavor is ever locally downloaded at a time.
  - Frontend: new `MeteorComparisonPanel.jsx`, sidebar step 7, gated on
    `state.overlay` loaded like ValidationPanel — but with its own
    `meteorComparison` state slice (never sharing `validation`'s), no
    event picker, and a prominent amber `panel__hint--warning` callout
    ("this checks agreement with another model ... not a check against
    real-world accuracy") using new `--color-warn`/`--color-warn-bg`
    tokens rather than borrowing the danger/error palette (nothing here
    has gone wrong). Reuses `SuccessRateChart`/`PrecisionRecallChart`/
    `validation-panel__*` CSS as-is.
  - `aucQuality()` extracted from ValidationPanel.jsx into a shared
    `lib/aucQuality.js` (both panels' AUC now read the same qualitative
    bands, rather than two copies that could drift).
  - **A real mislabeling bug caught by re-reading my own diff before
    calling this done, not by a test or the user**: `SuccessRateChart`,
    reused as-is for the METEOR panel, still said "Observed flooding
    captured" on its axis and "of the real observed flooding" in its
    tooltip -- exactly the "observed" vs "modeled" conflation this
    entire feature's own framing exists to avoid, just smuggled back in
    through a shared chart component's hardcoded text. Fixed by adding
    a `capturedLabel` prop (default `"real observed flooding"`,
    matching ValidationPanel's original text exactly) that
    MeteorComparisonPanel overrides to `"METEOR-modeled flooding"`.
  - Verified live end-to-end (headless-Chrome CDP): computed a single-
    criterion (`dem_elevation`) risk surface over central Kathmandu (no
    real UNOSAT extent there, but METEOR has modeled hazard everywhere
    in Nepal), ran Compare to METEOR, got a real, internally-consistent
    result (AUC 0.444, precision/IoU 0.13 matching METEOR's own 12.5%
    flooded fraction, recall 1.00, F1 0.22 matching the harmonic-mean
    formula exactly, flood_type/return_period label rendered as
    "Fluvial (Defended), 1-in-100y") -- screenshotted, confirmed the
    warning callout renders distinctly, and confirmed via a second AOI
    that POST /validate's own zero-observed-flooded error message kept
    its exact original wording (the `zero_positive_hint` default working
    as intended).
  - 5 new backend tests (`test_compare_meteor_router.py`, mirroring
    test_validate_router.py's own structure: aligned/opposite confusion
    matrices, 422 for an AOI outside METEOR's domain, 503 for a missing
    local file, and the compute-cache-reuse check). Full suite (464
    tests) green.
- **Bulk "Auto-classify all" action** (CriteriaPanel.jsx), at explicit
  request: an option, once an AOI is set (drawn, or selected via basin/
  district — all three set the same `state.aoi` shape, so this was
  deliberately never restricted to basin selection specifically) and at
  least one criterion is checked, to remake every checked continuous
  criterion's risk classes from that area's own real value distribution
  in one click, rather than opening each criterion's own "Customize
  breaks" section individually. Not new backend/data-fetch logic --
  `POST /api/overlay/criteria/breaks` (equal-interval/quantile/Jenks
  candidate breaks over the current AOI) already existed and was
  already reachable per-criterion; this is a frontend convenience layer
  over it.
  - Defaults to **Jenks Natural Breaks**, not Quantile or Equal
    Interval -- the one method actually named for and designed to find
    natural clusters in a variable's own distribution, the closest
    match to "remake the classes based on the features of that area."
    A method dropdown next to the button lets the bulk action use
    Equal Interval/Quantile instead, same as the per-criterion picker.
  - Categorical criteria (currently only `worldcover_land_cover`) are
    silently skipped -- no "breaks" concept applies to discrete land-
    cover codes, only manual per-code class assignment -- with a small
    hint noting how many were skipped and why, rather than erroring or
    pretending they were included.
  - Refactored `ClassificationEditor.jsx`'s own per-criterion method-
    switch logic (apply already-fetched breaks immediately if the
    method's data was already loaded for this AOI, otherwise just set
    the method and let the existing fetch effect pick it up -- a native
    `<details>` always mounts its children even while collapsed, so
    that effect runs regardless of whether "Customize breaks" happens
    to be expanded) out into a new shared `lib/classification.js`
    export, `selectClassificationMethod` -- both the per-criterion
    buttons and the new bulk action now take the exact same path,
    rather than two copies of this non-obvious behavior that could
    quietly drift apart.
  - A real premature-success bug caught before it shipped, not by a
    test: the bulk action's own "All N applied" summary was originally
    keyed on `entry.method === method` alone, which the button's click
    handler sets synchronously for every criterion on the same render
    -- criteria that still needed a fetch would flash "All N applied"
    for one render before their `fetch.status` ever left `'idle'`.
    Fixed by requiring `fetch.status === 'loaded'` too.
  - Verified live end-to-end (headless-Chrome CDP): drew a real AOI,
    checked Elevation, Slope, and Land Cover, clicked "Auto-classify
    all (2)" (Land Cover correctly excluded from the count), watched it
    genuinely take several real seconds (a real backend computation
    over real DEM/slope rasters, not instant), and confirmed real,
    area-specific Jenks breaks landed in each criterion's own break
    inputs (e.g. elevation breaks 1295/1438/1604/1811m against that
    AOI's own real 1105-2104m range) -- screenshotted. Also confirmed
    no regression on the per-criterion method buttons: switching
    Elevation to Equal Interval after the bulk fetch applied instantly
    (no re-fetch, reusing the same already-loaded response) with
    correctly equal-width breaks.
- **Validation methodology overhaul**, at explicit request, after real
  usage surfaced a real problem: an AUC of 0.556 had been computed
  against `nepal_2024_terai` for a Kathmandu-area risk surface -- the
  wrong reference AOI entirely (that event's own real geometry is
  Terai-only, already documented above), telling little about the
  surface it was supposedly validating. Three changes, together:
  - **AUC-ROC kept as the single PRIMARY statistic** (unchanged
    mechanics) -- confirmed as "conceptually correct for a
    susceptibility ranking" and kept front and center in both panels.
  - **A real Kathmandu-area validation reference, finally**: sourced
    live from Nepal's BIPAD Portal (`bipadportal.gov.np`), the national
    Disaster Information Management System owned by NDRRMA -- its own
    public, unauthenticated REST API (`/api/v1/incident/?hazard=11`)
    returns 2,999 verified flood-occurrence POINTS nationwide
    (2011-06-05 to 2026-08-24), 139 of them genuinely within Kathmandu
    Valley (checked directly, not assumed) -- the gap every prior
    source in `D:\New folder\README.md` hit. Registered as a new
    `nepal_bipad_flood_points` validation event
    (`app/data/config.py`). A real, live-verified finding along the
    way: `get_observed_flood_mask`/`get_validation_extent_geojson`
    (`validation_extent.py`) needed **zero code changes** for point
    geometries -- both geopandas' I/O and `rasterio.rasterize()` are
    already geometry-type-agnostic, confirmed with a direct test
    against the real file before registering it, not assumed.
    Full provenance (including the "license not formally verified,
    unlike UNOSAT's confirmed CC BY-SA" caveat) written up in
    `D:\New folder\README.md`'s own new section.
  - **Precision/recall/F1/IoU/PR-AUC removed entirely** (not caveated,
    not hidden behind a flag) from both `/validate` and
    `/compare-meteor` -- "the wrong question for a ranking, where the
    whole point is 5 ordered classes, not a single yes/no cutoff" was
    the standing critique; `app/overlay/confusion_metrics.py` (and its
    7 tests) deleted outright as a result, `success_rate.py` reverted
    to just `auc`/`curve` (its `zero_positive_hint` parameterization
    kept -- still needed for `meteor_comparison.py`'s own reuse of the
    AUC computation), `PrecisionRecallChart.jsx` deleted as dead code.
  - **New: frequency-ratio-per-class** (`app/overlay/frequency_ratio.py`)
    -- "does risk increase monotonically across classes", the
    literature-standard, directly communicable complement to AUC (Lee &
    Pradhan 2007's own method): for each hazard class 1-5, what
    fraction of that class's own pixels really flooded, plus a
    `monotonic` boolean. A class absent from the AOI gets
    `flooded_fraction: null`, never a misleading `0.0` conflating
    "doesn't occur here" with "occurs here and never floods" -- and is
    excluded from the monotonicity check itself, not treated as a
    sequence break.
  - Frontend: new `FrequencyRatioChart.jsx` (dataviz skill loaded and
    followed before writing it) -- a single-series bar chart, one bar
    per hazard class, each colored via the SAME
    `riskValueToCssColor((hazard_class-1)/4)` mapping
    CriterionSnapshot/ReportOverlay already use for a class swatch,
    not a chart-local palette; a class absent from the AOI draws as a
    hollow/dashed outline instead of a phantom zero-height bar; the
    y-axis auto-scales to the real data range rather than a fixed
    0-100%, since a point-inventory event's own fractions are
    genuinely tiny by design (formatting handled by a new shared
    `lib/formatFraction.js`, adaptive precision so a value like
    0.002% never silently rounds to a misleading "0.00%").
  - Both response models (`ValidateResponse`/`CompareMeteorResponse`)
    updated to match: `frequency_ratio`/`monotonic` added,
    `pr_auc`/`precision_recall_curve`/`precision`/`recall`/`f1`/`iou`/
    the 4 raw confusion-matrix pixel counts removed. An additive-only
    change this was not -- a real, intentional breaking change to both
    endpoints' response shape, done in one pass rather than deprecating
    fields gradually, since nothing outside this project's own frontend
    consumes them yet.
  - 8 new backend tests (`test_frequency_ratio.py`, hand-built hazard-
    class rasters including a real absent-class/monotonicity-skip
    case), `test_confusion_metrics.py` deleted, 3 PR-AUC-specific tests
    trimmed from `test_success_rate.py`, both router test files updated
    for the new response shape plus explicit `assert "precision" not in
    body`-style negative checks. Full suite (461 tests) green.
  - Verified live end-to-end (headless-Chrome CDP + direct curl against
    the real endpoint): a real Kathmandu AOI against the new BIPAD
    point event returned AUC 0.360-0.575 across different runs (a real,
    honest, un-inflated number -- one run scored below 0.5, reported
    plainly rather than smoothed over) with `monotonic: true`, and the
    same AOI against METEOR returned AUC 0.382-0.444 with its own
    frequency-ratio chart -- both screenshotted, confirming the chart
    renders correctly at real (often sub-0.01%) magnitudes and the
    warning callout/attribution/curve-label wiring from the prior two
    entries above all still work unchanged.
- **Landing page redesign**, at explicit request, using inunda.ai
  ("keeping this as the gold standard") as the visual reference --
  live-screenshotted through several scroll positions via headless-
  Chrome CDP first (a JS-rendered scrollytelling SPA WebFetch's own
  markdown conversion couldn't see) to actually extract its design
  language rather than guess at it: dark theme, huge centered
  typography, one concept per full-height screen, a small letterspaced
  eyebrow above each heading, generous negative space, a cyan/teal
  accent, a side scroll-progress-dot rail.
  - **Hero**: reordered to name -> tagline -> graphic -> supporting
    detail, per explicit request. New `HeroGraphic.jsx` -- a
    placeholder, not a final illustration (explicitly permitted) --
    built from the app's OWN existing visual language rather than a
    generic motif (an earlier hero illustration had been removed
    before this session for being exactly that, "not good enough"):
    5 concentric rings via `riskValueToCssColor`, the same ramp the
    map's own risk surface/hazard-class legend already use, with
    `Logo.jsx`'s own river-bend glyph traced across the middle at hero
    scale -- the same shape a viewer already saw small in the nav, not
    a second unrelated motif. A subtle CSS pulse animation, disabled
    under `prefers-reduced-motion`.
  - **Methodology expanded from 1 section (4 cards in a grid) to 4
    full-height scroll sections** -- "How to use it" / "What is AHP?"
    / "The method" (clusters) / "Criterion vs. validation" (METEOR) --
    matching inunda's own "one concept per screen" pattern instead of
    several ideas competing for attention on one screen. New shared
    `MethodScene` wrapper in `LandingPage.jsx` so a 5th scene later
    needs no new markup pattern.
  - **Dark theme confirmed already default** -- `initialTheme()`
    (`AppStateContext.jsx`) already defaults to `'dark'` from an
    earlier "midnight precision instrument" redesign decision predating
    this session; verified live, no code change needed.
  - **Every academic citation removed from the landing page itself**,
    at explicit request ("Sarlahi papers" -- the actual reference is
    Parajuli et al. 2023's Siraha Municipality study; not literally
    named "Sarlahi" anywhere in this codebase, but the same district-
    study citation) -- `(Saaty, 1980)` and `Parajuli et al. (2023)`
    both used to appear directly in the landing page's own prose (the
    latter reusing `METHOD_INTRO.body[0]` verbatim, sourced from
    `literature.js`, which is right for the in-tool `LiteratureModal`
    but wrong once citations are meant to live ONLY behind an info
    button). Both sentences rewritten citation-free for the landing
    page's own copy; the citations themselves aren't lost -- new
    `METHODOLOGY_CITATIONS` in `config/attribution.js` (copied verbatim
    from `backend/app/data/attribution.py`'s own constant of the same
    name) renders as a new "Methodology" group in `CreditsSection.jsx`,
    which only `AboutModal.jsx` (the in-tool ℹ️ "About this project"
    button) renders -- `LandingPage.jsx` builds its own separate markup
    from the same config data and never touches this new export.
    Data-source LICENSE attributions (Copernicus DEM, WorldCover, OSM,
    CHIRPS, ...) deliberately kept on the front page's own "Data
    sources" section -- a different category from a methodology paper
    citation, and required by several of those sources' own license
    terms -- with a new closing line pointing to the info button for
    the rest. Verified live: swept the entire rendered landing page's
    own text for "Parajuli"/"Saaty"/"et al" -- the only "et al" left is
    CHIRPS's own required attribution string, confirmed by locating it
    directly, not assumed.
  - **METEOR overlay map control now hidden unless "Flood Hazard
    (METEOR)" is checked as a criterion**, at explicit request (it
    previously always showed regardless of context, cluttering the map
    with a type/return-period/eye-toggle control for a layer that
    might not even be part of the current risk surface).
    `MeteorFloodControl` gained an `updateVisibility()` escape-hatch
    method (same "push updates in" pattern `ValidationExtentControl`'s
    own `updateEvents()` already uses) -- a plain container
    `display:none` toggle, not `map.addControl`/`removeControl`, so
    re-showing it never rebuilds its own two `<select>`s and loses
    whatever the user had picked. `TOGGLE_CRITERION`'s own reducer case
    also now force-resets `meteorFloodVisible` to `false` when METEOR
    is specifically unchecked, so the actual overlay layer can never be
    left silently "on" with its own toggle button no longer on screen
    to turn it back off. Verified live end-to-end: hidden by default,
    appears the instant the checkbox is checked, disappears the instant
    it's unchecked.
  - Frontend production build clean; no backend changes this entry.
- **Landing page follow-up corrections**, at explicit request, revising
  three specific pieces of the prior entry above:
  - **METEOR overlay control reverted to always-visible** -- the prior
    entry's "hidden unless the METEOR criterion is checked" gating was
    the wrong call; it's a standalone reference layer meant to be
    available regardless of current input selections, not tied to
    criteria state at all. That gating (the `updateVisibility()`
    escape hatch, its own ref/effect in `MapView.jsx`, and
    `TOGGLE_CRITERION`'s force-reset of `meteorFloodVisible`) removed
    outright, not just disabled. In its place: `MeteorFloodControl`
    simplified from a type + return-period + toggle 3-control cluster
    down to a single toggle, fixed to Fluvial (Defended), 1-in-100y --
    the one combination that actually matches the criterion's own
    local raw-data file (`backend/app/data/config.py`'s
    `METEOR_FLOOD_TYPE`/`METEOR_FLOOD_RETURN_PERIOD` defaults), so the
    map's reference overlay and the criterion (when checked) can never
    silently disagree about which METEOR flavor each is showing.
    `SET_METEOR_FLOOD_TYPE`/`SET_METEOR_FLOOD_RETURN_PERIOD` (now
    unreachable -- nothing dispatches them any more) removed from the
    reducer; `meteorFloodType`/`meteorFloodReturnPeriod` state kept
    (still read by `MeteorFloodLegend.jsx` and the tile-URL builder),
    just no longer writable via UI. Verified live: control visible
    with zero criteria checked, zero dropdowns, one toggle, correct
    fixed legend label, and the overlay itself genuinely renders on
    toggle.
  - **Hero section: continuous scroll-scrubbed scale**, at explicit
    request -- every other element on this page still uses
    `useScrollZoom.js`'s own binary IntersectionObserver reveal (a
    deliberate, documented prior design choice: universally supported,
    no per-frame listener cost), but the hero specifically now needs a
    genuinely continuous value tied to scroll position, which that
    mechanism can only coarsely approximate. New `useHeroScrollScale.js`
    -- a real (rAF-throttled) scroll listener, the one deliberate
    exception to the "no scroll listener" principle above, scoped to
    exactly one section rather than a pattern repeated per-section:
    tracks the hero's own `getBoundingClientRect().top` against its own
    height, maps that to `sin(progress * π)` so the whole hero content
    block (title, tagline, graphic, description, actions, facts,
    animated together as one group, not independently) scales from
    0.86 at the very top of the page, up to a true 1.0 peak exactly at
    the section's own scroll midpoint, back down to 0.86 by the time
    it's scrolled past -- verified live by sampling the actual computed
    `transform` at 6 scroll fractions (0, 0.25, 0.5, 0.75, 1.0, 1.2 of
    the hero's own height), confirming the peak lands precisely at 0.5
    and holds steady past 1.0 rather than overshooting. Applied via an
    inline style updated every frame, deliberately with NO CSS
    `transition` on it (would visibly lag behind/fight the already-
    smooth per-frame updates); disabled under `prefers-reduced-motion`
    the same way `useScrollZoom.js` already is.
  - **Team order: Bishesh Khanal moved to the middle position**, at
    explicit request -- `TEAM_CREDITS` (`config/attribution.js`,
    shared by both the landing page's own team-showcase grid and
    `CreditsSection.jsx`) reordered to Aayush / Bishesh / Anuj. Verified
    live in the rendered 3-across grid.
  - Frontend production build clean; no backend changes this entry.
- **Three small, real bugs fixed**, all at explicit report:
  - **BIPAD point inventory wasn't rendering on the map at all** -- a
    real, live-caught bug, not a sizing issue as first suspected: the
    validation-extent overlay's own layer (`MapView.jsx`) was `type:
    'fill'`, which renders NOTHING for Point/MultiPoint geometries in
    MapLibre (fill only applies to polygons) -- `nepal_2024_terai`
    (a polygon extent) always worked, `nepal_bipad_flood_points` (this
    session's own new point inventory) never had a chance to render at
    all regardless of point size. Fixed with a second layer on the same
    source, `type: 'circle'` (`VALIDATION_EXTENT_POINTS_LAYER`) --
    always added alongside the fill layer regardless of which event is
    loaded, not conditionally chosen by inspecting geometry type: a
    circle layer is itself already a safe no-op over polygon geometries
    the same way fill is a no-op over points, so both can coexist
    unconditionally. Sized deliberately large (7px radius, white
    stroke) for real visibility, per the report. Verified live:
    screenshotted real magenta circle markers rendering correctly over
    Kathmandu, tracing real BIPAD incident locations.
  - **Native `<select>` dropdown popups unreadable in dark mode** -- a
    real, live-caught bug: `.basemap-control__select` (and every other
    `<select>` in the app) correctly themes its own CLOSED box via this
    app's own CSS, but the native OPTIONS POPUP that appears on click
    is a separate browser-rendered surface outside that CSS's reach --
    without an explicit signal, most browsers render that popup with
    LIGHT-mode native defaults regardless of the page's own dark theme,
    putting this app's own light `--color-text` text on the browser's
    own light popup background: functionally invisible, matching the
    report exactly ("the dropdown menu is the same color as font").
    Fixed two ways: `color-scheme: dark`/`light` added to `:root`/
    `[data-theme='light']` (the browser-native, standards-based fix for
    exactly this class of problem), plus explicit `background`/`color`
    on `select option` as a defensive backup in case some browser
    doesn't fully honor `color-scheme` for popup content. Verified live
    via computed styles on a real `<option>` element (not just the
    declared CSS) -- background and text color now genuinely contrast.
  - **METEOR overlay control had no visible label** -- after last
    entry's simplification down to a single icon-only toggle button
    (dropdowns removed), the control lost all on-screen text, unlike
    every sibling control in the same group. Fixed with a plain
    `<span class="basemap-control__label">` showing "Fluvial
    (Defended), 1-in-100y" directly, not just in the hover title.
  - Frontend production build clean; no backend changes this entry.
- **Shelter identification** (`POST /api/overlay/shelters` + sidebar
  step 8 "Shelters") — the item SPEC.md's own status line had named as
  pending since the first version of this document. Ranks real OSM
  building footprints in the AOI as candidate emergency-shelter SITES
  by multi-criteria suitability: safety (the building's own hazard
  class, majority-overlap sampled — building_classification.py's exact
  rule, reused rather than reimplemented, so this feature and the
  vulnerability report can never disagree about a building's hazard
  class), accessibility (distance to the nearest road,
  distance_raster.py's existing dist_to_road machinery), and service
  value (local population density at the site, population.py). Any
  candidate sitting in a HIGH_RISK_CLASSES (4/5) hazard zone is
  excluded outright, never merely down-ranked — a site that is itself
  in the high/very-high hazard zone cannot be a safe shelter regardless
  of how it scores on the other two factors.
  - **Scope, explicit**: this identifies suitable SITES from the AOI's
    existing building stock, not existing tagged emergency shelters or
    shelter-TYPE buildings specifically (schools, hospitals, ...). This
    project's buildings dataset (`app/data/osm.py`'s `get_osm_features`)
    is geometry-only — no amenity/`building=school|hospital` tag
    survives through the FlatGeobuf extract pipeline this project's OSM
    tier already uses (§3.6's own osm.py write-up) — so a shelter-TYPE
    classification isn't derivable from data this project already has
    without a new data-engineering pass over the raw `.pbf`/shapefile
    export, not attempted here. Instead, a real building's own footprint
    area (computed on the UTM grid, never raw degrees — §2.1's CRS
    convention applies here too) must clear `config.
    SHELTER_MIN_FOOTPRINT_AREA_M2` (default 250 m², a structurally-
    reasonable, not-literature-calibrated placeholder, same documented-
    placeholder spirit as `DRAINAGE_DENSITY_THRESHOLD_CELLS`, per-
    request overridable) to be considered a candidate — standard
    practice for GIS shelter-siting when building-type attribution isn't
    available, but a site-suitability ranking, not a shelter-type
    classification, and documented as such so it's never mistaken for
    "these ARE existing shelters."
  - **Normalization, deliberately NOT the fixed-range [1,5] scale
    RiskSurface.value_range uses (§3.4)**: each of the three factors is
    min-max normalized across the AOI's own surviving candidates (a
    missing signal at one candidate's own location — e.g. a population
    coverage gap — scores at the midpoint 0.5, neither penalized nor
    favored for a data gap) and combined via a transparent weighted mean
    (equal thirds by default; `safety_weight`/`accessibility_weight`/
    `service_weight` are caller-overridable). This is a within-AOI
    ranking ("which of THESE buildings, in THIS area, is the better
    choice"), not a stored, cross-AOI-comparable score, so ordinary
    min-max normalization is the right tool — not a violation of
    RiskSurface's own fixed-range convention, which exists specifically
    to protect a DIFFERENT, cross-AOI-comparable value.
  - Reuses `compute_overlay`'s own risk-surface cache untouched, same
    shape `report.py`'s `compute_vulnerability_report` already
    established: submitting the same aoi/criteria/final_weights/
    complete already sent to `POST /compute` hits that cache rather than
    recomputing.
  - A real bug caught by this feature's own test suite before it
    shipped: `_min_max_normalize`'s "every present value is identical"
    branch originally scored every candidate at 1.0 (copy-pasted from
    the wrong branch) instead of 0.5 — silently telling every equally-
    scored candidate on that factor "you're the best," rather than "this
    factor has no discriminating signal here." Caught by
    `test_min_max_normalize_all_equal_scores_at_midpoint`, fixed before
    the module was otherwise touched again.
  - 13 new backend tests (`test_shelters.py`: exclusion of too-small and
    high-hazard buildings, ranking sensitivity to accessibility/
    population, the zero-roads-in-AOI None-not-excluded case, `top_n`
    truncation, and 5 direct `_min_max_normalize` unit tests including
    the bug above; `test_shelters_router.py`: the full endpoint end to
    end via FastAPI's TestClient, `min_footprint_area_m2`/`top_n`
    forwarding, and the shared `complete=False` rejection). Full suite
    (491 tests) green, zero regressions to the existing 478.
  - Frontend: `SheltersPanel.jsx` (sidebar step 8, gated on a loaded
    `state.overlay` exactly like `ReportPanel`/`ValidationPanel`,
    reusing the same `criteriaUsed`/`weightsUsed` snapshot so a shelter
    ranking can never describe a different result than what's on
    screen) renders the ranked list directly in the sidebar — compact
    enough (≤200 candidates) that it doesn't need `ReportOverlay`'s own
    map-covering-infographic treatment. `MapView.jsx` gained a
    `shelter-candidates` layer (a distinct amber fill, `#f5b301`,
    deliberately never the green-yellow-red hazard ramp any other layer
    here uses, so a candidate reads as its own category of thing, not
    one more hazard swatch) with rank-number labels and a click-to-
    inspect popup, toggleable independently of the classified-buildings
    layer the vulnerability report already has. New `shelters`/
    `sheltersLayerVisible` state (`AppStateContext.jsx`), same reset-on-
    `OVERLAY_LOADING` / auto-show-on-load shape `report`/
    `reportOverlayVisible` already established. Verified live end to
    end against the real running app (Docker, not a mock): a clean
    production `vite build` (258 modules, zero errors), and a real
    `POST /api/overlay/shelters` request against the live backend
    correctly rejected an incomplete weight set with the same
    `overlay_validation_error` shape `POST /compute` already returns.
- Frontend: **a quality-of-life pass** — 7 items from a larger QOL
  brainstorm the user asked for and then selected from, all shipped in
  one pass; an 8th item from that same brainstorm (splitting the
  sidebar's steps 5-8 into their own page — "landing page, then
  configuration page, then result page" — was explicitly deferred at
  the user's own request, "I'll work on it later," and is NOT done —
  see the note at the end of this entry).
  - **AOI persistence** (`state/AppStateContext.jsx`) — the single most
    annoying loss-of-work moment this app had: a page refresh silently
    threw away a drawn AOI, every checked criterion, and any AHP/manual
    weighting work, with zero warning. New `FLOW_STORAGE_KEY`
    (`'flood-risk-flow-v1'`, versioned, same try/catch-guarded
    `localStorage` shape `THEME_STORAGE_KEY` already established) persists
    exactly the "core flow" INPUT fields — `aoiMode`, `aoi`, `basinLevel`,
    `criteriaEnabled`, `streamThresholdCells`, `weightMode`,
    `ahpMatrices`, `manualWeights`, `classification` — on every relevant
    change, restored via `applyPersistedFlowState` in `initialState()`.
    Deliberately does **not** persist any fetched/computed RESULT
    (`overlay`, `report`, `validation`, `shelters`, `meteorComparison`,
    …) — those stay cheap to recompute from the restored inputs, and
    persisting a stale result risked it being shown as if still current.
    `applyPersistedFlowState` validates every field against the CURRENT
    `config/criteria.js` `CRITERIA` list before trusting it (a persisted
    blob from before a criterion was added/removed can't resurrect a
    dangling id or corrupt the restored shape) — `criteriaEnabled`/
    `classification`/`manualWeights` are filtered key-by-key, everything
    else is validated by exact expected type/enum before being applied.
    A real gap closed alongside this: `MapView.jsx`'s `DRAW_PREVIEW_SOURCE`
    (the layer that visually renders a drawn rectangle's outline) was
    only ever populated by the live mouse-drag interaction itself, never
    re-derived from `state.aoi` — so a restored draw-mode AOI would
    correctly `fitBounds` to the right area but show no visible boundary
    at all until redrawn. Fixed with a new mount-only effect that
    populates that same source from `state.aoi.bbox` via the existing
    `bboxToPolygon` helper when `state.aoi.source === 'draw'` — basin/
    district selections didn't need the equivalent, since their own
    selected-highlight layers are already keyed live off
    `state.aoi.basinId`/`districtPcode`, not a one-shot interaction
    result.
  - **Code-split the frontend bundle** (`App.jsx`) — the single
    ~1.26MB main chunk this SPEC previously flagged (mostly MapLibre GL
    + geotiff.js) was imported unconditionally at the top of `App.jsx`,
    so even a landing-page-only visit who never launches the tool paid
    for both libraries up front. `MapView`/`Sidebar`/`CitizenView`/
    `ReportOverlay`/`DataGapNotice`/`MeteorFloodLegend` are now
    `React.lazy()`-loaded behind a `<Suspense>` boundary (a plain
    themed "Loading…" fallback, `ViewLoadingFallback`), only fetched
    once a view that actually needs them is reached; `LandingPage`/
    `ModeSelect` stay eager, since they're the real first paint and are
    cheap on their own. Verified via a real production `vite build`:
    the main entry chunk dropped from 1,260KB (gzip 366KB) to 187KB
    (gzip 60KB), with `maplibre-gl` (802KB), `MapView`, `Sidebar`,
    `CitizenView`, and `rasterPreview` (geotiff.js) now separate chunks
    fetched on demand.
  - **Debounce/guard rapid re-computes** — `ComputePanel.jsx`'s own
    `handleCompute` already guarded itself (`if (disabled) return`) on
    top of the button's own `disabled` attribute; the same guard
    (`if (status === 'loading') return`) was missing from every other
    async trigger handler in the app (`ReportPanel`, `ValidationPanel`'s
    `handleValidate`, `MeteorComparisonPanel`, `SheltersPanel`) — a fast
    double-click/double-Enter before React's own disabled-attribute
    re-render lands could otherwise fire the same request twice. Closed
    on all four.
  - **Friendlier error messages + retry affordance** — new
    `lib/friendlyError.js` (`friendlyErrorMessage(error, fallback)`)
    translates an `ApiError`'s own `.code` (the backend's
    `HTTPException(detail={"error": ...})` string — `data_source_
    unavailable`, `overlay_validation_error`, `ahp_consistency_check_
    failed`, etc., one entry per code currently raised anywhere in
    `backend/app/*/router.py`) into a plain-language headline, while
    still surfacing the real backend message underneath (collapsed
    behind a `<details>`, never hidden — this project's own "document
    the real cause, never hide it" convention, applied to end-user-
    facing text too). An unmapped code or a plain network failure
    (`status === 0`, `api/client.js`'s own no-response case) both
    degrade to a sensible generic headline rather than crashing or
    showing nothing. New shared `components/ErrorNotice.jsx` (headline +
    collapsed detail + an optional one-click Retry button) replaces the
    bare `<p className="field-error">{error?.message || '...'}</p>`
    pattern repeated across the app — wired into `ComputePanel`,
    `ReportPanel`, `ValidationPanel` (both its events-list fetch and its
    validate action), `MeteorComparisonPanel`, `SheltersPanel`,
    `AOIPanel` (both its basins and districts fetches),
    `ClassificationEditor`'s per-criterion breaks fetch, and
    `CriterionSnapshot`'s raster-thumbnail fetch — 10 sites total, each
    now offering a real one-click retry of the exact same request
    rather than requiring a full re-navigation through the sidebar.
    `AHPPanel` is the one deliberate exception: its computation is
    reactive (`useAhpAutoCompute`, debounced, re-fires on any matrix
    edit), not a manual button trigger, so a Retry button has no clean
    action to bind to — it gets the friendlier headline only, with a
    comment explaining why no retry is offered there.
  - **First-visit tour** — new `components/FirstVisitTour.jsx`, a
    4-step walkthrough (Area of interest; Criteria & weighting; Compute;
    Report/Validate/Compare/Shelters) shown automatically the first time
    a visitor reaches the researcher tool view, gated on a third
    `localStorage` flag (`'flood-risk-tour-seen'`, same shape as
    `THEME_STORAGE_KEY`/`FLOW_STORAGE_KEY` above) so it never reappears
    for a returning visitor. Reuses `AboutModal`'s own `.modal-overlay`/
    `.modal` shell (a new narrower `.tour-modal` variant) rather than a
    second modal treatment invented for this one case; Escape/Skip/click-
    outside all dismiss and mark it seen, same as `AboutModal`'s own
    Escape handling.
  - **Dark-mode popup fix** (`index.css`) — a real, reported bug, not
    just unstyled chrome: MapLibre's own click-to-inspect popups (the
    classified-buildings and shelter-candidate popups, `MapView.jsx`)
    render via `maplibre-gl.css`'s hardcoded-WHITE popup-content box,
    but the popups' own inline HTML never set an explicit text color —
    it inherited this app's dark-theme body text color (near-white),
    producing white text on a white box, unreadable. Fixed with an
    explicit `.maplibregl-popup-content`/`.maplibregl-popup-tip`/
    `.maplibregl-popup-close-button` override block (this app's own
    `--color-panel`/`--color-text`/`--color-border` tokens, `!important`
    to override the library's own higher-specificity defaults — the
    exact same pattern this file's existing `.maplibregl-ctrl-*`
    overrides already use for the zoom/basemap/attribution chrome),
    legible in both themes regardless of what color the surrounding
    page happens to be using.
  - **Deferred, at the user's explicit request**: splitting the sidebar
    into "landing → configuration (steps 1-4) → results (steps 5-8)"
    across separate pages — a real architectural change (a new `view`
    state, the sidebar split in two, moving steps 5-8 and their own map
    layers to a second page, a "back to configure" path) big enough that
    the user asked to hold off and work on it themselves later, rather
    than have it land inside this same QOL pass. Not started; the
    current single-page sidebar (all 8 steps in one step-rail) is
    unchanged.
  - Verified live via two separate Playwright-in-Docker passes against
    the real running app (both hit the same environment limitation —
    this container's headless Chromium has no GPU/software rasterizer,
    so MapLibre's WebGL canvas never composites to a screenshot; each
    pass adapted around that rather than skipping verification
    entirely, noted per-item below):
    1. The lazy-loading split: landing → mode-select → tool view →
       citizen view, each transition confirmed loading correctly (a
       brief real "Loading…" Suspense flash, then the real view, no
       chunk-load 404s, no stuck fallback) with zero console errors.
       The one console error actually observed (`Failed to initialize
       WebGL`) was confirmed to be the sandbox's own GPU-less headless
       Chromium, not this diff — same failure reproduces regardless of
       the lazy-loading change.
    2. The AOI-persistence/tour/error-notice/popup-fix batch: the
       first-visit tour appeared automatically on first reaching the
       tool view and did not reappear after a reload (`localStorage`'s
       own `flood-risk-tour-seen` flag, confirmed set). AOI persistence
       itself was verified by setting a realistic AOI + 2 checked
       criteria directly into the real `flood-risk-flow-v1`
       `localStorage` key (the exact shape `AppStateContext.jsx` reads/
       writes — live mouse-drag drawing wasn't reliably exercisable in
       this same GPU-less sandbox) and confirming a reload correctly
       restored "AOI set (drawn area)" with the exact bbox, both
       criteria still checked, and weighting still complete. A real
       compute (Elevation only) and a real report generation both
       completed successfully (62,029 buildings classified) with zero
       console errors throughout. The popup dark-mode fix itself
       couldn't be screenshotted for the same WebGL/canvas reason
       (clicking a building feature on a canvas that never visually
       renders isn't reliable), so was confirmed by direct inspection
       of `index.css`'s own popup override block and this app's actual
       dark-theme token values (`--color-panel`/`--color-text`) instead
       — the fix is genuinely dark-background/light-text, not
       white-on-white, confirmed against the real values rather than
       assumed correct from the diff alone.
    Frontend production build clean throughout (261 modules, zero
    errors); no backend changes this entry.
- **Shelter-candidate map highlight**, at explicit follow-up request
  ("make it so that the shelters are highlighted") — a real building's
  own small footprint (`SHELTERS_FILL_LAYER`, §above) can be genuinely
  hard to spot at anything but a close zoom, especially against a busy
  basemap. `MapView.jsx` gained a new animated highlight layer
  (`SHELTERS_HIGHLIGHT_LAYER`, a `circle` layer at each candidate's
  approximate centroid — new `lib/geo.js` export `polygonCentroid`, a
  cheap plain-average-of-ring-vertices centroid, good enough for
  marker placement though not a true area-weighted one) rendered
  *beneath* the footprint fill/rank-label layers so the pulse reads as
  radiating out from behind each building, not painted over it. Pulses
  via `requestAnimationFrame` (`startShelterHighlightPulse`, ticking
  `circle-radius`/`circle-opacity` on a smooth sine wave, 1.8s period)
  — MapLibre's own canvas-rendered paint properties have no CSS-
  keyframe equivalent, so this is one of only two places in this file
  (alongside the landing page's own `useHeroScrollScale.js`) that ticks
  a paint property directly rather than relying on a CSS transition;
  respects `prefers-reduced-motion` the same way that hook does (a
  fixed, still-visible radius/opacity, never a suppressed one). The
  animation loop is started once per shelters result (inside the same
  effect that (re)creates the layer) and always cancelled — both on a
  new result replacing it and on unmount — via a ref holding the
  current `requestAnimationFrame` handle, so it can never keep ticking
  a paint property on a layer that no longer exists. The highlight
  layer is also click/hover-bound identically to the footprint fill
  layer (same popup content either way), so the whole visibly-
  highlighted area is clickable, not only a real building's own small
  footprint. Frontend production build clean; no backend changes.
- Not yet implemented: shelter-TYPE classification (distinct from the
  site-suitability ranking §3.7 already documents), and the deferred
  landing/configuration/results page split noted above. The GeoTIFF
  file route is a simple direct-read endpoint, not a general static-
  asset server or CDN — fine for local dev and this phase's needs, but
  worth revisiting if the cache grows large or needs to be served from
  object storage in a real deployment. The `drainage_density`/`hand`
  stream-extraction threshold and moving-window radius are
  structurally-reasonable placeholders, not literature-calibrated
  values (§3.6) — pending real calibration against a known Kathmandu
  Valley stream network.
