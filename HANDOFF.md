# FloodHUB — Session Handoff

Written at ~90% context usage in the session that just finished the
vulnerability-report feature, a real population-density bug fix, a
basemap picker, and live compute progress streaming — all committed
and pushed (`48c25e7` on `main`). This document is the technical
briefing for the **next** Claude Code session, which will focus on a
**visual redesign** of the frontend. Read `SPEC.md` (the project's own
living spec/changelog, ~1000+ lines) for full narrative detail on any
item below — this document is the condensed, redesign-focused map of
the codebase, not a replacement for it.

**Environment**: Windows 11, PowerShell primary shell, Bash tool also
available (POSIX). Project root: `c:\important documents\AcademicCV_Bishesh`.
Runs via `docker compose up -d` (3 services: `backend`, `frontend`,
`db`). Backend on `http://localhost:8000`, frontend dev server on
`http://localhost:5173`. `git status` should be clean at handoff time
— if not, check `git log -1` and `git diff` before doing anything else.

---

## 1. Project context

**FloodHUB** (formerly "flood risk mapping — Kathmandu Valley", renamed
mid-project — the GitHub repo is `FloodHUBnepal`) is a GIS web tool
that computes a **flood risk map** for a user-selected area in Nepal,
using a multi-criteria weighted-overlay method (AHP — Analytic
Hierarchy Process), then derives a **vulnerability/exposure report**
from that risk surface (hazard-class-tagged buildings, population and
area per hazard class). It is a real scientific methodology
implementation (matching a "Siraha-style" flood susceptibility mapping
approach referred to in the code as "the Siraha paper" — Parajuli et
al., 2023, ISPRS Int. J. Geo-Inf. 12(7), 286, doi:10.3390/ijgi12070286,
open access CC BY 4.0; cited in full in
`backend/app/data/attribution.py`'s `METHODOLOGY_CITATIONS`. It is still
not shown in the app's Credits section, but that is now a product
choice, not a missing-citation blocker), not a toy demo.

**Architecture**: FastAPI (Python 3.12) backend + React (Vite, plain
JS not TypeScript) frontend + PostGIS (currently unused by the app's
own logic — provisioned but no table/model reads from it yet) +
Docker Compose for local dev. No auth, no user accounts, no
persistence of AOIs or past results (explicitly "not yet implemented").

**Backend stack**: FastAPI, Pydantic v2, rasterio (GDAL bindings),
geopandas, shapely, numpy, scipy, pandas, pyogrio, pyrosm (OSM `.pbf`
parsing), pysheds (hydrology/flow routing), jenkspy (Jenks natural
breaks). Python 3.12 in the container; a Windows-native Python 3.10
also exists on the host and was used for host-side data-prep scripts
this session (see §2's OSM section) — don't assume host and container
Python have identical installed packages.

**Frontend stack**: React 18 + Vite 5, plain CSS (no Tailwind/CSS-in-JS
— see §4), MapLibre GL JS 4.7 for the map, `geotiff` npm package to
decode returned GeoTIFFs client-side for rendering, `proj4` for
coordinate transforms. No React Router — single-page state machine
(`view: 'landing' | 'tool'` in `App.jsx`). No component library, no
design tokens beyond a hand-rolled CSS custom-property system (§4).

**Geographic scope**: Nepal generally (HydroBASINS covers the whole
country, no area cap on basin selections — see §3), with Kathmandu
Valley as the practical pilot/demo area (test fixtures, default map
center, most live-verification this session used Kathmandu-area AOIs).

---

## 2. Current implementation

### What's implemented and working (verified live this session, not
just unit-tested)

- **AOI selection**: draw a rectangle on the map (capped at 1000 km²),
  or select a real HydroBASINS Level-8 basin polygon (no area cap —
  basins are exempt from the cap entirely, a deliberate decision this
  session; see SPEC.md's Phase-3-area section). Basin selection uses
  the basin's **true polygon shape**, not its bounding box — both for
  display and for masking the final risk surface (a basin's result
  now visually follows the basin's real shape on the map, not a
  rectangle).
- **14 criterion sources** (this line is a point-in-time count, kept
  loosely in sync — SPEC.md §3.6's own table is the source of truth),
  each independently cached per-AOI and reprojected onto a common
  analysis grid: `dem_elevation`, `dem_slope` (Copernicus GLO-30 DEM,
  live S3), `worldcover_land_cover` (ESA WorldCover, live S3),
  `dist_to_river`, `dist_to_road` (OSM, local `.pbf`/pre-processed
  FlatGeobuf fast path/R2 fallback), `twi`, `drainage_density`, `hand`
  (pysheds-derived hydrology), `building_density` (OSM buildings),
  `population_density` (Meta/CIESIN HRSL, live S3), `ndvi` (Sentinel-2
  L2A), `soil_infiltration` (ISRIC SoilGrids), `rainfall` (DHM
  gauge-network IDW interpolation), `precipitation_chirps` (CHIRPS
  satellite climatology). Registered via a **pluggable registry**
  (`app/overlay/sources.py`'s `register_source`) — adding a 15th
  source needs zero changes to the overlay engine itself.
- **AHP weighting** (2-level hierarchy: 5 canonical clusters
  {Topographic, Hydrological, Land Use, Infrastructure, Exposure}, then
  criteria within each cluster the user selected), computed via the
  eigenvector method (Saaty 1980) with consistency-ratio validation
  (CR < 0.10, Saaty's Random Index table). Also supports **equal
  weights** and **manual/typed weights** modes — three weighting modes
  total in the frontend (`state.weightMode: 'equal' | 'ahp' | 'manual'`).
- **Weighted-overlay risk surface computation**: `R = Σ(weight_i *
  class_i)`, normalized to `R_norm = (R-1)/(5-1)` ∈ [0,1]. Cached by a
  SHA-256 hash of (AOI bbox + true polygon + criteria set + weights +
  **reclassification_rules fingerprint** — a real bug fixed this
  session, see §3).
- **Discrete hazard-class derivation** (1-5, round-nearest inverse of
  the R_norm formula) + **building-level classification** via
  majority-overlap spatial join (not centroid — verified live to
  matter for large/elongated buildings) + **zonal statistics**
  (area/population/building-count per hazard class) + a full
  **computation report** assembling all of this plus AOI/criteria/
  weighting context. See §3 for the full scientific pipeline.
- **Live compute progress**: real Server-Sent Events streamed from the
  backend as each criterion resolves (not a fake animated bar) — see
  §2's API list, `POST /api/overlay/compute/stream`.
- **GeoTIFF downloads**: both the continuous risk surface and the
  discrete hazard-class raster are downloadable.
- **Basemap picker**: 5 free basemaps (Street/OSM, Light/CARTO
  Positron, Dark/CARTO Dark Matter, Satellite/Esri World Imagery,
  Topographic/OpenTopoMap), independent of the app's own light/dark
  theme, plus a show/hide toggle for the basemap layer.
- **Landing page** ("FloodHUB" branding, hero, Credits section with
  team photos/LinkedIn/data attribution) separate from the tool itself
  (`App.jsx`'s `view` state toggles between them).

### What's tested

**281 backend tests passing** (pytest, `backend/tests/`), zero known
regressions as of the last commit. Run via (inside the backend
container or host Python with the same deps):
```
cd backend && python -m pytest -q -m "not slow and not network"
```
`-m slow` tests hit real live network endpoints (S3, R2) — run
separately, not part of the default suite. No frontend automated test
suite exists (no Jest/Vitest/Playwright test files committed) — all
frontend verification this session was done via ad hoc Playwright
scripts run through a throwaway `mcr.microsoft.com/playwright` Docker
container (screenshots + console-error checks), not committed
anywhere. **If the next session wants repeatable frontend tests, that
infrastructure doesn't exist yet.**

### Important existing files (backend)

- `app/main.py` — FastAPI app, CORS (allows `localhost:5173`/
  `127.0.0.1:5173` + `CORS_EXTRA_ORIGINS` env var), mounts 4 routers.
- `app/ahp/` — `core.py` (eigenvector/consistency math), `hierarchy.py`
  (2-level composition), `constants.py` (Random Index table, the 5
  canonical cluster names), `models.py`/`router.py` (API layer).
- `app/basins/` — `models.py`/`router.py` (both level 8 and level 9,
  selected via a `level` query param), backed by `app/data/basins.py`
  (HydroBASINS shapefiles + an OCHA/HDX Nepal-boundary refinement — CC
  BY-IGO, commercial-use-safe, replacing an earlier HERMES source that
  was non-commercial-use-only — for edge-basin support-status
  classification).
- `app/districts/` — `models.py`/`router.py`, backed by
  `app/data/districts.py` (Nepal's 77 districts, from the same HDX file's
  admin-level-2 layer) — a second AOI-selection alternative alongside
  basins, mirroring that package's own split.
- `app/common/aoi.py` — `AOIInput` Pydantic model shared by every
  endpoint that accepts an AOI; enforces the 1000 km² cap (bbox-only
  AOIs; polygon-bearing/basin AOIs are exempt).
- `app/data/` — one module per raw data source
  (`dem.py`/`worldcover.py`/`osm.py`/`population.py`/`hydrology.py`/
  `density_raster.py`/`distance_raster.py`), each following the same
  "local-check-first, then live cloud fallback" pattern (see
  `local_source.py`'s shared helper). `grid.py` is the common
  10m/EPSG:32645 analysis grid. `reclassify.py` is the generic
  continuous/categorical → 1-5 class engine, driven entirely by a
  criterion's `reclassification_rules`, never hardcoded per criterion.
  `cache.py` is the shared per-AOI disk cache (`backend/data/cache/
  processed/`, pickle files, gitignored, fully regenerable).
- `app/overlay/` — the composition/orchestration layer:
  `sources.py` (the pluggable registry), `compute.py` (pure weighted-
  sum math, `RISK_CLASS_MIN/MAX = 1/5`, `RISK_SURFACE_NODATA = -9999.0`,
  `compute_cache_key`), `service.py` (`compute_overlay` —
  the main orchestration function, now with an optional `on_progress`
  callback param), `hazard_classes.py`/`building_classification.py`/
  `zonal_stats.py`/`report.py` (the vulnerability-report pipeline, all
  new this session), `progress_stream.py` (SSE bridging), `breaks.py`
  (equal-interval/quantile/Jenks candidate reclassification breaks),
  `geotiff.py`, `models.py` (all Pydantic request/response shapes),
  `router.py`, `urls.py`, `errors.py`.

### Important existing files (frontend)

- `App.jsx` — top-level, `view: 'landing'|'tool'` state.
- `state/AppStateContext.jsx` — **the single source of truth**, one
  `useReducer`, exposed via context. Read this file first before
  touching any state-driven behavior. Key state shape: `theme`,
  `basemapStyle`/`basemapVisible`, `aoiMode`/`aoi`/`selectedBasinId`,
  `criteriaEnabled` (map of id→bool), `weightMode`/`ahpMatrices`/`ahp`
  (AHP compute result)/`manualWeights`, `classification` (per-criterion
  reclassification-rule editing state), `overlay` (compute
  status/result/`progressLog`), `report` (vulnerability-report
  status/result). `useFinalWeights()` and `useSelectedCriteriaIds()`
  are the two derived-state hooks other components read.
- `config/criteria.js` — **the only place criterion display names/
  clusters/units/default reclassification rules live** — the backend
  has no such registry (confirmed explicitly this session while
  building the report feature; the report's `name`/`cluster` fields
  are optional pass-throughs the frontend supplies). `CANONICAL_CLUSTERS`
  here must exactly match `app/ahp/constants.py`'s.
- `components/MapView.jsx` — all MapLibre-specific code: basemap
  (`BASEMAPS` registry + `BasemapControl` custom `IControl`), draw-AOI
  interaction, basin polygon layer, risk-surface raster overlay
  (decoded client-side via the `geotiff` package + `lib/colorRamp.js`).
- `components/Sidebar.jsx` — the panel stack:
  `AOIPanel → CriteriaPanel → WeightingPanel → ComputePanel +
  ResultPanel → ReportPanel`, each gated on the previous step having
  something to act on. **This numbered-step top-to-bottom flow is the
  entire current UI structure** — see §4/§6 for why this is the
  primary redesign target.
- `components/ComputePanel.jsx` — the compute button + live progress
  log (uses `computeOverlayStream`, not `computeOverlay`).
- `components/ReportPanel.jsx` — the "Generate report" button +
  zonal-stats table + headline stats + weighting breakdown display.
- `api/client.js` — thin fetch wrappers, one function per backend
  endpoint, **deliberately no abstraction library** (see file's own
  header comment: "Thin fetch wrappers... No mocking/stubbing"). Has a
  hand-rolled SSE-over-`fetch()` parser (`computeOverlayStream`) since
  the browser's native `EventSource` doesn't support POST bodies.
- `lib/colorRamp.js`, `lib/geo.js`, `lib/proj.js`, `lib/classification.js`,
  `lib/ahpMatrix.js` — small pure-function helpers, no side effects.

### Full current API surface

```
POST /api/ahp/compute                                  — AHP weight computation
GET  /api/basins                                        — all basins, GeoJSON FeatureCollection
GET  /api/basins/{hybas_id}                              — one basin's detail
GET  /api/basins/{hybas_id}/aoi                          — {bbox, polygon} ready for AOIInput
POST /api/overlay/compute                                — risk surface (plain JSON)
POST /api/overlay/compute/stream                         — SAME computation, Server-Sent Events
POST /api/overlay/criteria/breaks                        — candidate reclassification breaks
GET  /api/overlay/risk_surface/{cache_key}.tif            — continuous [0,1] GeoTIFF download
GET  /api/overlay/hazard_classes/{cache_key}.tif          — discrete 1-5 GeoTIFF download
POST /api/overlay/report                                  — full vulnerability report
```

`POST /compute` and `POST /compute/stream` do the *same* computation —
the streaming one is what the frontend actually uses interactively;
the plain one stays for any non-interactive caller and is what
`report.py` calls internally (its own `compute_overlay` call has no
`on_progress`, so it's silent — the report's own heavier follow-up
work isn't currently progress-streamed at all; only the base compute
button is).

### Data flow for one full user session (mental model)

1. User draws/selects AOI → `SET_AOI` → `state.aoi` set, `state.overlay`
   reset to idle.
2. User checks criteria → `TOGGLE_CRITERION` → `state.criteriaEnabled`,
   `state.classification[id]` seeded with default reclassification
   rules from `criteria.js`.
3. User picks a weighting mode → AHP mode triggers
   `state/useAhpAutoCompute.js` (a hook watching `ahpMatrices`,
   auto-calling `POST /api/ahp/compute` and dispatching
   `AHP_LOADED`/`AHP_ERROR`).
4. `useFinalWeights()` derives the actual `final_weights` dict to
   submit, handling all 3 modes (see that hook's own extensive
   comments in `AppStateContext.jsx` — AHP mode renormalizes over just
   the selected criteria when some cluster is empty; this matters a
   lot for the backend's consistency-check, see §3).
5. `ComputePanel`'s button → `computeOverlayStream` → live progress →
   `OVERLAY_LOADED` with the result (includes `data_url`,
   `hazard_classes_data_url`, `cache_key`).
6. `ResultPanel` renders the reclassification breakdown, legend,
   attribution, and download links. `MapView` renders the raster.
7. `ReportPanel`'s "Generate report" button → `POST /api/overlay/report`
   (reuses the SAME cache_key/risk-surface computation — a cache hit
   if params match) → zonal table, headline stats, weighting
   breakdown, its own download links.

---

## 3. Scientific logic (DO NOT CHANGE without explicit instruction)

This section is the part most likely to be silently broken by a
"redesign" that touches component logic, not just styling. Read it
before moving/refactoring ANY component that renders scientific
output.

### AHP workflow
- 2-level hierarchy: top-level pairwise comparison of the 5 canonical
  clusters, then one pairwise comparison per cluster among its
  selected criteria.
- **Eigenvector method is primary** (Saaty 1980) — the principal
  eigenvector of each Saaty pairwise matrix, normalized to sum to 1.
  An "approximate" column-normalize-and-average method is also
  computed and returned but is **diagnostic only**, never used
  downstream (Jensen 1984 is cited as the reason the exact method is
  preferred).
- **Consistency Ratio must be < 0.10** (`CONSISTENCY_RATIO_THRESHOLD`
  in `ahp/constants.py`) or the backend rejects the matrix with a 422
  and reports the least-consistent judgment(s) (`worst_pairs`, per
  Saaty 2003's epsilon_ij formula). This is a hard requirement, not a
  warning, for `POST /api/ahp/compute` and the report's own AHP
  recompute.
- `final_weight(criterion) = cluster_weight(criterion.cluster) *
  within_cluster_weight(criterion)`.
- **A cluster with zero selected criteria is normal, not an error** —
  Exposure was empty for most of this project's history until
  `population_density`/`building_density` were added. When this
  happens, the frontend's `useFinalWeights` **renormalizes** the raw
  AHP output over just the selected criteria (the top-level
  comparison "spent" some weight mass on the empty cluster with
  nothing to receive it). **This renormalization is why the backend's
  weighting-consistency-check had to be fixed mid-session** (see
  below) — comparing raw un-renormalized AHP output against the
  frontend's renormalized `final_weights` produces false-positive
  "mismatch" warnings on the single most common real usage pattern.
  If you touch `useFinalWeights` or the report's consistency check,
  re-read `app/overlay/report.py`'s `_weighting_consistency_warning`
  docstring in full first.

### Weighting methods
Three, all producing a `final_weights: dict[criterion_id, float]`
summing to 1: `equal` (1/n), `ahp` (above), `manual` (raw typed values,
normalized to sum to 1). The backend's `ReportWeightingInput.method`
accepts all three literal strings — the AHP-specific fields
(`cluster_comparison`/`within_cluster_comparisons`) are optional and
only meaningful when `method == "ahp"`.

### Overlay / risk calculation
```
R = Σ(weight_i * class_i)          class_i ∈ {1,2,3,4,5} per criterion
R_norm = (R - 1) / (5 - 1)         normalized to [0, 1]
```
This is a **weighted BLEND across criteria at each pixel**, not a
single criterion's own class — a pixel can have elevation=class 3 and
distance-to-river=class 5 simultaneously, and R_norm reflects their
weighted average, never either alone. `RISK_SURFACE_NODATA = -9999.0`
propagates via an **any-nodata-poisons-the-pixel** rule
(`compute_risk_surface`'s `any_nodata`): if ANY contributing
criterion is nodata at a pixel, the whole pixel is nodata in the
output, regardless of what other criteria say there. This is
deliberate and load-bearing — do not "fix" a sparse-looking risk
surface by changing this rule; instead check whether a SOURCE's own
nodata semantics are wrong (see the population.py bug below — that
was the actual right fix).

### Classification (reclassification)
`app/data/reclassify.py`'s `apply_reclassification` is fully generic,
driven only by `reclassification_rules` (never a hardcoded per-
criterion table). A rule: `{min, max, min_inclusive, max_inclusive,
risk_class}`. `min`/`max` of `None` mean unbounded. A **categorical**
rule set (any rule has `min == max`, e.g. a discrete land-cover code)
skips the "gap-free coverage" check that a **continuous** rule set
(range-based) must satisfy — every value in the domain needs a rule,
or the backend raises rather than silently leaving a pixel
unclassified. `RECLASSIFIED_NODATA = 0` (risk classes are 1-5, so 0 is
unambiguous). **Grid resampling convention (SPEC.md §2.2, load-bearing)**:
continuous data → bilinear; categorical/already-reclassified data →
nearest-neighbor only, never averaged. **Count-type data (like raw
population count) must be converted to a density BEFORE bilinear
resampling** — resampling a raw count directly silently stops being a
count at all (doesn't conserve total, doesn't divide correctly across
finer output pixels). `population.py`'s `_count_to_density` is the
reference implementation any future count-type source should copy.

### Vulnerability analysis (this session's main feature)
"Vulnerability" here means **hazard-zone exposure classification**
(interpretation confirmed explicitly by the user this session): which
buildings/people fall in which discrete hazard class — **NOT** a
separate building-quality/susceptibility dimension. Pipeline:
1. `hazard_classes.py`: invert R_norm back to discrete classes 1-5,
   **round-nearest** (not floor — floor was explicitly rejected as
   systematically biased down; documented in the module).
   `HAZARD_CLASS_LABELS`: 1=Very Low, 2=Low, 3=Moderate, 4=High,
   5=Very High.
2. `building_classification.py`: each OSM building tagged with the
   hazard class its footprint falls in, via **majority-overlap** (one
   labeled-rasterize pass + vectorized groupby-mode, not a per-building
   loop) — chosen over centroid sampling because a large/elongated
   building can straddle a class boundary; verified live this actually
   changes the answer for a hand-constructed test case. Ties resolve
   to the **higher** class (never understate risk). A footprint too
   small to rasterize to any pixel falls back to centroid sampling.
3. `zonal_stats.py`: per-class area/population/building-count.
   **Population = Σ(density × pixel_area_km²), never a raw Σ(density)**
   — the same count-vs-density unit correction, one layer up.
4. `report.py`: assembles everything, including the AHP consistency
   check (see above) and a **cluster** derivation for each criterion
   (only knowable when `weighting.method == "ahp"`, derived from
   `within_cluster_comparisons`' own `items` lists — the backend has
   no other source of criterion→cluster mapping).

### Data-source correctness notes (real bugs found + fixed this session)
- **`compute_cache_key` used to hash only `criterion_id` + `weight`**,
  never `reclassification_rules` — two requests with different
  breakpoints for the same criterion collided on the same cache and
  served stale results. Fixed by folding in
  `reclassify.rules_fingerprint()`. If you ever touch caching, re-read
  this fix (SPEC.md, search "risk-surface cache key").
- **HRSL (`population_density`) nodata means "not a detected
  settlement" (a confirmed zero), not "unknown"** — verified against
  the raw source directly (before any reprojection) and against
  Meta/CIESIN's own technical documentation. The pipeline used to
  treat it as unknown, propagating it as output nodata, which then
  poisoned the whole risk surface at that pixel via the any-nodata
  rule — using `population_density` as a criterion left ~50% of any
  AOI with no risk score at all. Fixed in `_count_to_density`.
  **Do not revert this without re-reading the reasoning** — it's a
  genuine, source-specific data-semantics fact, not a guess.
- OSM data has a 3-tier local-check-first fallback (pre-processed
  FlatGeobuf → raw `.pbf` via pyrosm → R2), because parsing a raw
  `.pbf` for one AOI took 145-210s; the FlatGeobuf tier is 0.01-4.4s.
  This tier system is genuinely load-bearing for interactive use —
  don't simplify it away without understanding why it exists
  (SPEC.md's OSM section has the full story).

---

## 4. Current UI

### Page structure
- **Landing page** (`view: 'landing'`): hero (FloodHUB name/logo,
  Kathmandu Valley subtitle), a "Launch tool" button, `CreditsSection`
  (team photos + LinkedIn + data-source attribution + HydroBASINS/
  Nepal-boundary credits). No methodology citations shown yet
  (deliberate, pending real bibliographic detail for the drainage-
  density reference).
- **Tool page** (`view: 'tool'`): a fixed-width (420px) left `Sidebar`
  + a flex-grow `MapView` filling the rest of the viewport. This is
  the ENTIRE layout — no responsive breakpoints for narrow viewports
  beyond one `@media` block late in `index.css` (line ~1248), no
  mobile-specific design.
- Sidebar is a strict numbered top-to-bottom flow: `1. Area of
  interest → 2. Criteria → 3. Weighting → 4. Compute → 5.
  Vulnerability report`, each section only rendered once the previous
  one has something to act on (`state.aoi` set, then
  `selectedIds.length > 0`, then `state.overlay.status === 'loaded'`).
  An "About" modal (ℹ️ button, top-right of sidebar header) surfaces
  the same `CreditsSection` from inside the tool.

### Existing components (all under `frontend/src/components/`)
`AOIPanel`, `CriteriaPanel`, `WeightingPanel` (+ its children
`AHPPanel`, `PairwiseMatrixEditor`, `ManualWeightsPanel`),
`ClassificationEditor` (the "Customize breaks" expandable per
criterion), `ReclassificationTable`, `ComputePanel`, `ResultPanel`,
`ReportPanel`, `MapView`, `Sidebar`, `LandingPage`, `CreditsSection`,
`AboutModal`, `Logo`.

### Current design system (`frontend/src/index.css`, ~1400 lines by now)
A hand-rolled CSS custom-property token system (introduced in an
earlier "visual identity + landing page redesign" phase, not this
session): type scale (`--text-xs` through presumably `--text-lg`/
`--text-md`), spacing scale (`--space-1` through `--space-4`+),
`--radius-sm`, `--shadow-sm`, a teal/terracotta color palette
(`--color-primary`, `--color-accent`, `--color-danger`, `--color-bg`/
`--color-bg-alt`, `--color-panel`/`--color-panel-alt`, `--color-text`/
`--color-text-muted`, `--color-border`) deliberately distinct from the
risk-surface color ramp (`lib/colorRamp.js`) so UI chrome is never
mistaken for a risk value. Both light and dark theme variants defined
(`:root` + a dark-mode block, toggled via `data-theme` attribute on
`<html>`, driven by `state.theme`). Fonts: `--font-display` ('Space
Grotesk'), `--font-body` ('Inter'). No `--font-mono` token exists yet
(the new compute-progress log falls back to a bare `monospace` — a
gap worth filling if the redesign introduces real monospace UI, e.g.
for logs/code/coordinates).

### What currently works visually (verified this session)
Landing page, AOI drawing/basin selection, criteria checkboxes +
break-customization, all 3 weighting modes, compute button + live
progress log, risk-surface raster rendering (colorized via
`colorRamp.js`), download links, vulnerability report panel (headline
stat cards, zonal table, weighting breakdown), basemap picker (5
providers + visibility toggle), both light and dark theme — all
screenshot-verified working with zero browser console errors as of
the last commit.

### Known UI/UX problems (why a redesign is wanted)
- Sidebar is 420px fixed-width dense forms — very "SaaS admin panel,"
  not "scientific cartography tool." No visual hierarchy beyond plain
  `<h3>`/`<h4>` numbered headers.
  '**Small quantitative UI touches likely need real design thinking**:
  the zonal-stats table, headline stat cards (`ReportPanel.jsx`), the
  weighting breakdown list, and the reclassification tables are all
  currently bare HTML tables/lists with minimal styling — genuinely
  data-dense scientific output that a "professional geospatial app"
  aesthetic should treat as first-class, not an afterthought.
- Map controls are minimal: MapLibre's own zoom control + this
  session's new basemap-picker control (top-left, a bare native
  `<select>` + emoji toggle button — functional, not visually
  considered).
- No responsive/desktop-first consideration beyond one late `@media`
  block — confirm current behavior before assuming it's fine at
  various widths.
- The frontend bundle isn't code-split (~1.1MB main chunk, mostly
  MapLibre GL + geotiff.js) — a pre-existing, documented, deliberately
  deferred concern, not something introduced this session.
- No frontend automated tests (see §2) — a redesign has no regression
  safety net beyond manual/Playwright-script re-verification.

---

## 5. Design redesign goal

FloodHUB should be redesigned as a **professional scientific
geospatial application**, not a generic SaaS dashboard. Design
inspiration (principles only — do not copy branding, code, assets, or
exact layouts) from: **Climate Central**, **First Street / Flood
Factor**, **SPADACE**, **Mapbox-quality cartography**, **Nepal
BIPAD**. The next session should look at these independently (this
session did not research them) before proposing a design system.

---

## 6. Design direction

- Map-first interface (the map is the primary artifact; the sidebar
  should feel like a precision instrument panel alongside it, not the
  main event competing with it for space).
- Professional scientific aesthetic — sophisticated typography,
  restrained color use, strong information hierarchy, minimal clutter.
- Excellent map controls (the current basemap picker + zoom control
  are functional but visually an afterthought — a real design pass
  should treat this as a first-class UI surface, the way Mapbox Studio
  or a serious GIS tool would).
- Professional risk visualization — the risk-surface color ramp
  (`lib/colorRamp.js`) and the vulnerability report's data tables/stat
  cards are the actual scientific payload of this app; they deserve
  real cartographic/data-viz design attention, not default browser
  table styling.
- Responsive, desktop-first (this is a professional analysis tool, not
  a mobile app — but shouldn't visibly break at reasonable desktop
  widths either).
- The AOI → criteria → weighting → analysis → results → report
  workflow should read clearly as a **guided scientific process**, not
  a settings form — this is the throughline the current numbered-
  sidebar-sections structure gestures at but doesn't fully realize
  visually.

---

## 7. Redesign requirements (hard constraints)

- **Preserve the existing backend entirely** — no API contract
  changes without a very deliberate, explicit reason. Every endpoint
  in §2's list, every request/response shape in `app/overlay/models.py`
  /`app/ahp/models.py`/`app/basins/models.py`, stays as-is.
- **Do not change any scientific calculation** — §3 in full. If a
  redesign seems to require a calculation change, stop and ask rather
  than assume — this project has a strong "verify live before
  believing anything" and "flag decisions before finishing a phase"
  culture (see this repo's own git history/SPEC.md for the pattern);
  match it.
- **Reuse working functionality** — the state management
  (`AppStateContext.jsx`), the API client (`api/client.js`), and the
  actual DATA FLOW (§2's numbered walkthrough) should stay conceptually
  intact. A redesign is a **presentation-layer** pass, matching this
  project's own precedent (an earlier phase's redesign was explicitly
  scoped as "a design pass only, no data flow/state/API changes" —
  follow that same discipline).
- **Improve the frontend rather than rebuilding unnecessarily** — this
  is a real, working, live-verified application with 281 passing
  backend tests and a genuinely correct scientific pipeline behind it.
  A ground-up rewrite would throw that away for no reason. Prefer
  restyling/restructuring existing components over replacing them,
  unless a specific component's own logic is tangled with its
  presentation in a way that makes that impossible (if so, say so
  explicitly rather than silently rewriting).

---

## 8. Instructions for the next session

Work through these in order, and don't skip straight to visual changes
before the first four:

**A. Inspect the repository.** Read this document in full, then read
`SPEC.md` (long, but it's the authoritative project history/decision
log — every non-obvious choice in this codebase is explained there
with its reasoning). Check `git log --oneline -20` and `git status`
for anything that changed between this handoff being written and the
new session starting.

**B. Run the application.** `docker compose up -d` from the project
root; verify all 3 containers healthy (`docker compose ps`, then
`curl http://localhost:8000/` and `curl http://localhost:5173/` both
200). If the backend crashes or `docker compose logs backend` shows
errors, check first whether `backend/data/raw/`'s local source files
(DEM/WorldCover/OSM/population/basins) are present — many are
gitignored, machine-local, and the app degrades to live-cloud-fetch
paths without them, which is fine but slower. Also check the host's
C: drive free space before doing anything disk-heavy — this was a
recurring, real problem this session (the drive was found completely
full more than once, unrelated to this project's own footprint).

**C. Inspect the current UI.** Click through the actual real app in a
real browser (not just screenshots in this doc) — draw an AOI, select
criteria, try all 3 weighting modes, compute, generate a report, try
the basemap picker, toggle dark mode. Get a first-hand feel for what
§4 describes before proposing changes to it.

**D. Review the existing implementation.** Read `AppStateContext.jsx`
in full (it's the map of everything), then `Sidebar.jsx` and its
direct children, then `MapView.jsx`. Cross-reference against §2/§3
here for what NOT to break.

**E. Create a design audit.** A short, concrete document (or just a
clear plan) of what's visually weak today and why, referencing actual
components/files — not generic "improve the UI" language.

**F. Propose the design system.** Tokens (type/color/spacing/
elevation), grounded in the redesign inspiration in §5 but original,
not copied. Decide whether to extend the existing `index.css` token
system or introduce something new — extending is probably lower-risk
given how much of the app already reads through those tokens (an
earlier redesign phase deliberately built it so "none of those
component files needed logic changes, since they were already driven
entirely by class names" — a real, valuable property worth preserving
again this time).

**G. Implement the redesign incrementally.** Component by component or
section by section, not a single giant rewrite — this matches the
whole project's own established working style (small, verified,
committed increments) and makes it possible to catch a regression
early rather than at the end.

**H. Test every existing workflow after each meaningful change** — the
full AOI → criteria → weighting → compute → report flow, in both
light and dark mode, ideally via the same kind of throwaway Playwright-
in-Docker verification this session used repeatedly (screenshot +
console-error check; see any of this session's own verification calls
for the exact pattern — launch `mcr.microsoft.com/playwright`, route
`localhost:8000` to `host.docker.internal:8000` if running the browser
in its own container, since a containerized browser can't reach the
host's own `localhost`).

**I. Visually inspect the final result** before considering the
redesign done — take real screenshots, look at them, don't assume a
code change looks right without seeing it rendered.

---

## Appendix: SPEC.md navigation guide

`SPEC.md` is long (1000+ lines) and grows with every phase — don't
read it linearly under time pressure; jump to what's relevant:

```
§1  Repository layout
§2.1 CRS convention (EPSG:4326 in/out, EPSG:32645 internal — a
     redesign should never need to touch this, but good to know if
     any UI ever shows raw coordinates)
§2.2 Grid/resolution convention — the bilinear-vs-nearest-neighbor
     rule and the count-vs-density rule (§3 of this handoff, above)
§2.3 Nodata handling — the project-wide "never silently assume nodata
     means anything without checking" convention
§3.1-3.4 The 4 JSON Schemas (schemas/*.schema.json) — the canonical
     data-contract definitions AOIInput/Criterion/PairwiseMatrix/
     RiskSurface Pydantic models are meant to mirror. If a redesign
     ever needs a NEW field on a request/response, the schema file
     should be updated too, not just the Pydantic model.
§3.5 Basin-based AOI selection — the true-shape masking story
§3.6 Criterion sources & the pluggable registry — how to read (not
     necessarily how to add one; §2 of this handoff already covers
     that) each of the 9 sources' own local-check-first/cloud-fallback
     pattern
§4  Local development (docker compose usage, env vars)
§5  Status — a chronological log of every phase, MOST RECENT LAST.
     The tail end of this section (last ~400 lines as of this commit)
     covers everything from this session: population_density,
     basin true-shape/no-cap, OSM FlatGeobuf speedup, R2 fallback,
     the risk-surface cache-key bug fix, the vulnerability report
     feature, the population nodata bug fix, the basemap picker, and
     live compute progress streaming — in that order. Read backwards
     from the end if you only have time for the most recent, most
     load-bearing decisions.
```

## Appendix: key request/response shapes

Field names exactly as the Pydantic models define them (backend) /
as the frontend constructs them — useful for redesign work that needs
to know what data is actually available to render, without re-reading
the full model files.

**`POST /api/overlay/compute` request** (`OverlayComputeRequest`,
`app/overlay/models.py`):
```
aoi: { bbox: [minx,miny,maxx,maxy], polygon: GeoJSON|null }
criteria: [{ id, source, reclassification_rules: [{min,max,
             min_inclusive,max_inclusive,risk_class}] }]
final_weights: { [criterion_id]: float }   // must sum to 1
complete: bool
```

**`POST /api/overlay/compute` / `.../compute/stream` "done" event
response** (`OverlayComputeResponse`):
```
cache_key: str (64-char hex)
data_url: str                      // risk surface GeoTIFF path
hazard_classes_data_url: str       // discrete-class GeoTIFF path
grid: { crs, resolution_m, origin_x, origin_y, width, height }
nodata_value: float
value_range: [0.0, 1.0]
attribution: [str]                 // deduplicated source citations
source_warnings: [{ criterion_id, message }]
```
Streaming-only progress events (`.../compute/stream` only):
`{"type":"progress","message":str}` zero or more times, then exactly
one of `{"type":"done","result": <above shape>}` or
`{"type":"error","error":str,"message":str}`.

**`POST /api/overlay/report` request** (`VulnerabilityReportRequest`):
```
aoi, criteria (SAME as compute, but each criterion may also carry an
  optional `name: str` — the ONLY place a human display name for a
  criterion reaches the backend), final_weights, complete   // same as compute
weighting: {
  method: "equal" | "ahp" | "manual",
  cluster_comparison?: { items: [str], matrix: [[float]] },        // ahp only
  within_cluster_comparisons?: { [cluster]: {items,matrix} },      // ahp only
}
hybas_id: int | null            // if AOI came from a basin
support_status: str | null      // that basin's support_status
```

**`POST /api/overlay/report` response** (`VulnerabilityReportResponse`)
— the big one, most relevant to redesigning `ReportPanel.jsx`:
```
cache_key, generated_at (ISO-8601), risk_surface_data_url, hazard_classes_data_url
aoi: { bbox, polygon, area_km2, hybas_id, support_status }
criteria: [{ id, name, source, cluster, reclassification_rules }]
weighting: {
  method, final_weights,
  ahp_cluster_comparison: PairwiseResultOut | null,        // full AHP math detail
  ahp_within_cluster_comparisons: { [cluster]: PairwiseResultOut } | null,
  consistency_warning: str | null,      // see §3's AHP renormalization note
}
zonal_stats: [ { hazard_class (1-5), hazard_label, area_km2, population,
                 building_count } ]     // ALWAYS all 5, zero-filled if empty
buildings: { type:"FeatureCollection", features: [{ type:"Feature",
             geometry, properties:{hazard_class, hazard_label} }] }
             // can be tens of thousands of features (87,402 in one
             // live test this session) -- NOT currently rendered on
             // the map, only summarized in zonal_stats; a redesign
             // that wants a building-level map layer needs to think
             // about performance for that count.
total_buildings, total_population, total_area_km2
high_risk_building_count, high_risk_building_pct   // classes 4+5
high_risk_population, high_risk_population_pct     // classes 4+5
attribution: [str]
```
`PairwiseResultOut` (nested above, and also `POST /api/ahp/compute`'s
own per-matrix response shape): `items, matrix, eigenvector_weights,
approximate_weights, lambda_max, consistency_index, random_index,
consistency_ratio, consistent (bool), worst_pairs: [{item_i,item_j,
judgment,epsilon}]`.

**`POST /api/ahp/compute` request/response** — same
`cluster_comparison`/`within_cluster_comparisons` shape as the
report's `weighting` field above; response is
`{cluster_comparison: PairwiseResultOut, within_cluster_comparisons:
{[cluster]: PairwiseResultOut}, final_weights, complete, missing_clusters}`.

**`GET /api/basins/{hybas_id}/aoi` response**: `{bbox, polygon}` —
paste-compatible straight into any `aoi` field above.

## Appendix: frontend component quick-reference

For each `Sidebar.jsx` child, its main props/state reads and the one
thing most likely to matter for a redesign:

- **`AOIPanel`** — reads/writes `state.aoiMode`/`aoi`/`selectedBasinId`/
  `basins`. Two sub-modes (draw vs. select-basin) are currently plain
  tab-like buttons; drawing interaction itself lives in `MapView.jsx`,
  not here (this panel is mostly status display + the mode switch).
- **`CriteriaPanel`** — renders `CRITERIA` (from `config/criteria.js`)
  grouped by cluster, checkboxes bound to `state.criteriaEnabled`, each
  with a `ClassificationEditor` (collapsed by default, "Customize
  breaks") for `reclassification_rules` editing. This is the single
  densest form-heavy panel in the app — the clearest single target for
  "data-dense scientific UI" design treatment mentioned in §4/§6.
- **`WeightingPanel`** — a tab switch across `AHPPanel` (pairwise
  matrix editors — `PairwiseMatrixEditor` renders an actual N×N Saaty-
  scale matrix input grid, non-trivial custom UI), `ManualWeightsPanel`
  (plain number inputs), and the equal-weights case (no sub-panel, just
  a computed display). `PairwiseMatrixEditor` is probably the single
  most "needs real design thinking" custom widget in the app — matrix
  input UIs are inherently hard to make elegant.
- **`ComputePanel`** — button + `state.overlay.progressLog` rendered as
  a `<ul>` with ✓/⏳ prefixes, auto-scrolling (`useRef` + `useEffect`
  scrolling to `scrollHeight`). Disabled-state reasoning is somewhat
  complex (missing AOI vs. incomplete weights vs. unordered custom
  breaks) — `disabledReason` computation is worth preserving exactly,
  not just the button's visual state.
- **`ResultPanel`** — reads `state.overlay.result`/`criteriaUsed`/
  `weightsUsed` (a SNAPSHOT taken at compute time, deliberately not the
  live panels' current values — see this file's own header comment).
  Renders the color-ramp legend, per-criterion reclassification
  breakdown (`ReclassificationTable`, one per criterion, in a
  `<details>`), attribution list, and the two GeoTIFF download links.
- **`ReportPanel`** — gated on `state.overlay.status === 'loaded'`.
  Builds the full `VulnerabilityReportRequest` from already-captured
  compute-time state (not live panel state, for the same "never
  describe a different result than what's on screen" reason). Renders
  4 stat cards (total buildings, high-risk buildings, high-risk
  population, total area), a 5-row zonal table, and a weighting
  breakdown list.
- **`MapView`** — the only component that touches MapLibre directly.
  Owns 3 custom MapLibre sources/layers beyond the basemap: draw-
  preview (rectangle-in-progress), basins (fill + line, colored by
  `support_status` via `lib/colorRamp.js`'s `SUPPORT_STATUS_COLORS`),
  and the risk-surface raster (decoded client-side from the GeoTIFF
  bytes via the `geotiff` npm package, colorized via
  `riskValueToRgb`). A redesign touching the map's own visual language
  (basin fill colors, risk-surface color ramp, draw-rectangle style)
  should edit `lib/colorRamp.js` and the paint properties in this file
  — not introduce a second source of truth for either.

## Appendix: things a fresh session might not otherwise know

- **Windows path quoting**: this repo lives at a path with a space
  (`c:\important documents\...`) — always quote it in Bash/PowerShell.
- **CRLF warnings on every git commit** are expected/harmless
  (Windows `core.autocrlf` behavior) — not a sign of a problem.
- **Docker networking gotcha**: a browser running inside its own
  Docker container (e.g. for Playwright verification) cannot reach
  `localhost:8000`/`localhost:5173` — those resolve to the container
  itself. Use `host.docker.internal` (with `--add-host=host.docker.
  internal:host-gateway` on the `docker run`) instead, or route
  requests through Playwright's own `page.route()` interception if the
  app's own code hardcodes `localhost:8000` (the frontend's
  `API_BASE_URL` default does, deliberately, since a REAL user's
  browser on the host needs exactly that).
- **Cache invalidation when changing a result-class shape**: several
  `app/data/*.py` modules pickle-cache their results
  (`backend/data/cache/processed/`, gitignored). Renaming/changing a
  result dataclass's fields without clearing the relevant cache
  subdirectory causes a real `AttributeError` on unpickling stale
  data — this bit this session more than once. When in doubt,
  `rm -rf backend/data/cache/processed/<name>` is always safe (fully
  regenerable, never source data).
- **`.env` / `docker-compose.yml`**: local dev secrets/config via a
  gitignored `.env`, defaults baked into `docker-compose.yml`. R2
  (Cloudflare) env vars exist for OSM's fallback tier but are
  deliberately left unconfigured — the user's stated preference is to
  defer creating actual external cloud accounts until deployment time,
  even though the code path is fully built and tested.
- The user's name is Bishesh Khanal; two collaborators (Aayush Roka,
  Anuj Thapa) are credited in the landing page's Credits section with
  real photos/LinkedIn links — don't regenerate or alter those without
  reason, they're real people's real information.
