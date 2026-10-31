# Khola — GitHub Pages research demo

A React/Vite site showing precomputed susceptibility and district exposure across Nepal. It has **no Python service, database, API keys, account system or live analysis**. Optional satellite background tiles are fetched directly from Esri World Imagery when selected; the default neutral background makes no third-party tile requests. The separate application in `../frontend` and `../backend` retains its own build and behavior.

## Preview and verify

Node 24+ and npm:

```sh
cd pages-demo
npm ci
npm test
npm run build -- --base /FloodHUBnepal/
npm run preview -- --base /FloodHUBnepal/
```

Open `http://localhost:4173/FloodHUBnepal/`. For development, `npm run dev` serves the demo at the root. The `--base` argument must match the Pages repository path; use `/` for an account-root site or custom domain.

Browser checks use Playwright. Locally they use an installed Chrome; set `CI=1` and run `npx playwright install chromium` to use bundled Chromium instead. Build with `/FloodHUBnepal/` first, then run `npm run test:browser`. Tests check actual results, scheme/metric changes, keyboard selection, mobile layout, static downloads, error recovery and absence of live API requests. No browser tests make a call to the Python backend.

## Publish

The live URL is `https://bisheshkhanal036-afk.github.io/FloodHUBnepal/` (verified 2026-10-31). Source changes are available in [draft PR #5](https://github.com/bisheshkhanal036-afk/FloodHUBnepal/pull/5); publishing the generated site does not require merging the application’s default branch.

GitHub Pages serves only the built `dist/` contents from the root of the `gh-pages` branch, including `.nojekyll`. Repository **Settings → Pages → Source** should be **Deploy from a branch**, branch **gh-pages**, folder **/ (root)**. This uses GitHub's Pages branch build rather than requiring a custom workflow or workflow-write token scope.

Do not publish the repository root or raw-data directory as the site. For updates, rerun the build and update the generated `gh-pages` branch with `dist/`; a normal source push alone does not refresh the site. The deployment source is `pages-demo/`, not the live application build in `frontend/dist/`.

On Windows, after `gh auth login` and Git author/credential setup, `./scripts/publish-pages.ps1` installs dependencies, runs unit tests, builds and publishes the static site from a fresh temporary checkout. It retains old hashed assets on subsequent updates to avoid breaking already-open tabs. It does not publish your working branch or the rest of the repository. Browser checks are a separate verification step before release.

## Method and data

Committed files in `public/demo/` are a fixed **2026-10-31** research snapshot:

- Simplified outlines for 77 districts, joined by administrative p-code.
- Five precomputed schemes: expert median, Nepal-only expert median, equal eight-criterion weights, fitted cluster and fitted full reference weights.
- Research **national breaks**, **classes 4–5**, and **census-calibrated population**. The initial selected scheme is expert median. The denominator for mapped shares is the valid mapped area or population, not unknown cells.
- Coverage is disclosed. The research records one missing unit, 133.758 km² inside Nepal. Zero/missing denominators are shown as unavailable, not low susceptibility.
- Four original research figures, copied unchanged. No raw BIPAD records, individual shelter coordinates, user uploads or unpublished manuscript files are included.

The default map shows **precomputed cell-level susceptibility** for five schemes. Its 0.0025? overview cells (about 250 m) sample the nearest valid native 10 m cell without smoothing. Zooming enlarges this overview. Transparent gaps are unknown or outside the analysis domain. The separate district exposure layer colors **district aggregates**. An absolute population map reflects population concentration as well as classification. High susceptibility is not current flooding, a calibrated probability, or an evacuation recommendation. Fitted weights are study outputs, not a universally superior or forecast model. Shelter figures compare list stability; they do not designate approved shelters.

Boundary attribution: **Survey Department of Nepal; UN Resident Coordinator's Office in Nepal**, distributed by OCHA HDX in [Nepal — Subnational Administrative Boundaries](https://data.humdata.org/dataset/cod-ab-npl), **CC BY-IGO**. Public dataset metadata was checked during export preparation. Outlines are simplified with approximately 0.002° tolerance and rounded to four decimal places, for display only. Research calculations are already completed; these simplified boundaries never recalculate metrics.

Source file names and SHA-256 fingerprints are recorded in `public/demo/snapshot.json`; aggregate district/scheme values are downloadable as `district-exposure.csv`. This is an illustrative research publication, not fresh validation of the source study.

## Refresh the snapshot

`npm run demo:export` is a **local preparation command**, requiring the source checkout's `results/rq3_exposure_by_district.csv`, `rq3_national_totals.csv`, `rq3_coverage_note.csv`, four selected figures, and the configured HDX district shapefile under `backend/data/raw/basins/npl_admin_boundaries.shp/`.

It exports only explicitly selected aggregate columns, simplified boundaries and figures. It validates 77 unique district IDs and exactly one matching row per district/scheme. A clean GitHub checkout builds from the committed exports and does not need any raw geospatial data. When refreshing, update the documented snapshot date and verify figures, source attribution, coverage and tests before publishing. Refreshing the demo never runs the analysis pipeline.


### Regenerate susceptibility overviews

Install Python `numpy pillow pyproj pyshp`, then run `python scripts/export-hazard.py` from this folder with the canonical Tier A NPZ caches and HydroBASINS L8/L9 shapefiles available locally. The exporter validates every reconstructed native grid against its cache shape, uses the published national breaks and RQ3 weighting inputs, and produces five transparent indexed PNGs plus a methods/provenance manifest. It does not train a model or fetch new inputs. Classification follows RQ3: round weighted score to ten decimals, then floor(score + 0.5), clipped to classes 1?5. Run `python scripts/test_hazard_export.py` to verify classification boundaries and artifacts. `npm run demo:export` preserves the hazard manifest in the snapshot. All generated files are committed for server-free builds.


### Basin views and map navigation

The Leaflet map supports dragging, double-click/pinch zoom, keyboard pan/zoom, Shift-drag box zoom, zoom to district, and an enlarged map. Choose among 366 cached HydroBASINS L8/L9 research units to fit their full outlines. IDs are retained because these research units do not all have verified river names. Raster coverage remains Nepal-only even when a full basin crosses the border. Boundary overlays are switchable between districts, research basins and none.

The classification selector switches between national breaks and cached per-basin quintiles for all five schemes. Basin-relative classes describe variation within each research unit; class changes at basin boundaries can be expected. National and district summary cards continue to use national breaks, as labeled. The selected basin note is not a basin exposure total.

`python scripts/export-hazard.py` exports both classifications in geographic and Web Mercator display variants. Mercator variants explicitly resample rows with nearest-neighbor lookup so a geographic PNG is not incorrectly stretched over satellite tiles. `python scripts/export-basins.py` writes simplified basin outlines and the source attribution to `public/demo/basins.json`. The overview remains about 250 m regardless of zoom.

Satellite imagery: Esri, Vantor, Earthstar Geographics, and the GIS User Community. Current attribution was verified against the public World Imagery service metadata. Imagery is contextual, not live flood imagery. Switching to None removes the external tile layer. Tile failures are disclosed without disabling local raster and vector layers. HydroBASINS attribution and source links are shown when basin boundaries are enabled. See https://www.hydrosheds.org/products/hydrobasins and https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer .
