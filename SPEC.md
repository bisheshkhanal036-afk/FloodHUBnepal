# SPEC — Flood Risk Mapping & Shelter Identification, Kathmandu Valley

Status: **Backend (AHP engine, geospatial data layer with 12 registered
criterion sources, overlay engine, vulnerability-classification/reporting)
and a working, redesigned frontend map UI implemented; shelter
identification still pending** — see §5. This document defines
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

### 3.5 Basin-based AOI selection — `backend/app/data/basins.py`, `backend/app/basins/`

An **alternative** way to produce an AOI, alongside hand-drawing a bbox —
not a replacement. Backed by HydroBASINS Asia, level 8 (polygon
watershed boundaries — 28,907 basins; ~547 overlap Nepal's rough
extent), loaded once from a local shapefile (`config.LOCAL_BASINS_PATH`,
override via `BASINS_SHAPEFILE_PATH`) and cached in memory; there is no
cloud fallback for basins (unlike DEM/WorldCover/OSM) — a missing/invalid
file is a clear 503, not a degraded live-query path.

| Endpoint | Returns |
|---|---|
| `GET /api/basins` | GeoJSON `FeatureCollection` of basins overlapping Nepal's *rough* extent (a generous bbox screen, not a hard restriction — cross-border basins are kept whole, never clipped), each tagged with `support_status`. Real-data payload is ~3.9 MB at full geometry resolution regardless of caching (no simplification/pagination implemented — deferred, no clear need yet); response time is ~4s cold, ~0.17s once `get_basin_support_status`/`get_basin_pct_in_nepal`'s per-HYBAS_ID cache is warm (§ below). |
| `GET /api/basins/{hybas_id}` | One basin's detail: area (true polygon area, km²), `pct_in_nepal`, `support_status`, geometry. |
| `GET /api/basins/{hybas_id}/aoi` | `{bbox, polygon}` — the exact shape `AOIInput` (§3.1) accepts, so a selected basin drops straight into `POST /api/overlay/compute`'s `aoi` field unchanged. |

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
reasoning. Real-data breakdown across the ~547 basins overlapping
Nepal's rough extent: 155 `fully_in_nepal`, 41 `partial_likely_adequate`,
351 `likely_degraded_at_edges` — expected for a rectangular screening
filter against a mountainous country's actual (much smaller, irregular)
territory.

**Nepal's true boundary source**: HERMES
(https://download.hermes.com.np) — **non-commercial use only, no
redistribution without consent** per that site's license. Never
committed to this repo (`backend/data/raw/` is gitignored); swap in a
commercially-usable boundary (e.g. OCHA/HDX, Natural Earth) before any
commercial deployment.

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

### 3.6 Criterion sources & the pluggable registry — `backend/app/overlay/sources.py`

A `Criterion.source` (§3.2) is resolved to its raw physical layer through
a small, explicit, **pluggable** registry — `register_source(name, fn)`
maps a source name to a `(AOI) -> (raw_array, grid, nodata, attribution,
warning)` function (`warning` is `str | None`, `None` for every source
except `twi`/`drainage_density`, see below); `resolve_criterion_raster`
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
  density technique reference) are deliberately left out for now at the
  user's request ("don't cite papers yet") — the drainage-density
  reference in particular only has an informal "the Siraha paper"
  mention in `backend/app/data/hydrology.py`, no full bibliographic
  details anywhere in this codebase, and shouldn't be published as a
  citation until those are supplied. `index.css` was rewritten around
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
- Not yet implemented: AOI persistence, and shelter identification. The
  GeoTIFF file route is a simple
  direct-read endpoint, not a general static-asset server or CDN — fine
  for local dev and this phase's needs, but worth revisiting if the
  cache grows large or needs to be served from object storage in a real
  deployment. The `drainage_density`/`hand` stream-extraction threshold
  and moving-window radius are structurally-reasonable placeholders, not
  literature-calibrated values (§3.6) — pending real calibration against
  a known Kathmandu Valley stream network. The frontend's bundle
  (~1.1MB main chunk, mostly MapLibre GL + geotiff.js) isn't code-split
  — fine for local dev, worth revisiting before any real deployment.
