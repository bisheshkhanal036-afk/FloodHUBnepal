# Khola — GitHub Pages research demo

A self-contained React/Vite site showing precomputed district exposure across Nepal. It has **no Python service, database, map-tile service, API keys, account system or live analysis**. The separate application in `../frontend` and `../backend` retains its own build and behavior.

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

The intended URL is `https://bisheshkhanal036-afk.github.io/FloodHUBnepal/`.

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

The map colors **district aggregates**, not 10 m susceptibility pixels. An absolute population map reflects population concentration as well as classification. High susceptibility is not current flooding, a calibrated probability, or an evacuation recommendation. Fitted weights are study outputs, not a universally superior or forecast model. Shelter figures compare list stability; they do not designate approved shelters.

Boundary attribution: **Survey Department of Nepal; UN Resident Coordinator's Office in Nepal**, distributed by OCHA HDX in [Nepal — Subnational Administrative Boundaries](https://data.humdata.org/dataset/cod-ab-npl), **CC BY-IGO**. Public dataset metadata was checked during export preparation. Outlines are simplified with approximately 0.002° tolerance and rounded to four decimal places, for display only. Research calculations are already completed; these simplified boundaries never recalculate metrics.

Source file names and SHA-256 fingerprints are recorded in `public/demo/snapshot.json`; aggregate district/scheme values are downloadable as `district-exposure.csv`. This is an illustrative research publication, not fresh validation of the source study.

## Refresh the snapshot

`npm run demo:export` is a **local preparation command**, requiring the source checkout's `results/rq3_exposure_by_district.csv`, `rq3_national_totals.csv`, `rq3_coverage_note.csv`, four selected figures, and the configured HDX district shapefile under `backend/data/raw/basins/npl_admin_boundaries.shp/`.

It exports only explicitly selected aggregate columns, simplified boundaries and figures. It validates 77 unique district IDs and exactly one matching row per district/scheme. A clean GitHub checkout builds from the committed exports and does not need any raw geospatial data. When refreshing, update the documented snapshot date and verify figures, source attribution, coverage and tests before publishing. Refreshing the demo never runs the analysis pipeline.
