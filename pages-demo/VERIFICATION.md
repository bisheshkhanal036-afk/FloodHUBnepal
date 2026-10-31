# Static demo verification — 2026-10-31

- Export: 77 unique districts, five precomputed weighting schemes, four original figures.
- Unit/component tests: **13 passed** (actual snapshot validation, aggregate sums, ranking/filtering, missing denominators, paths, UI state, loading/retry).
- Production build: **passed** at `/FloodHUBnepal/`, the GitHub Pages project subpath.
- Browser tests: **4 passed**, local headless Chrome. Scheme/metric changes, district selection, keyboard map selection, table search, figure loading, static downloads, missing-snapshot retry and 390 px mobile layout were exercised.
- The browser request audit saw only same-origin requests, no `/api/` traffic and no localhost:8000 requests. No backend, account, key, external font or tile provider is needed.
- The default map viewport is checked to contain all district paths; zoom controls and reset are exercised.
- Desktop/mobile screenshots were captured and visually inspected. Initial review found an overly tall default map and mobile line-break spacing; corrected before release.
- Published assets total approximately 2.4 MB, including the existing project icon and four figures. This excludes development dependencies and source datasets.
- Boundary metadata was retrieved from OCHA HDX's dataset API: CC BY-IGO, Survey Department of Nepal / UN Resident Coordinator's Office in Nepal. Attribution and display simplification are disclosed in the UI and export notes.

This verifies the static presentation and data wiring, not the scientific validity of the underlying research. The displayed aggregates are the committed research outputs, not recomputed metrics, forecasts, incident records or operational shelter instructions.

Reproduction: `npm ci`, `npm test`, `npm run build -- --base /FloodHUBnepal/`, `npm run test:browser` (Node 24+, Chrome locally; see README for bundled Chromium).

## Public deployment check

GitHub Pages deployment run **41172081916** completed successfully from `gh-pages`.
Chrome checked `https://bisheshkhanal036-afk.github.io/FloodHUBnepal/` on 2026-10-31:
HTTP 200; 77 districts; five schemes; 385 downloadable district/scheme CSV rows;
scheme/district switching and research figures working; zero JavaScript runtime
errors; zero API requests; no page overflow at 390 px. Live desktop/mobile
screenshots are retained locally under `test-results/`. Recheck with
`node scripts/check-live.mjs`.

Source changes are on `feat/github-pages-demo`, draft PR #5; the application’s
default branch was not merged or replaced. The site is independently published
from its generated `gh-pages` branch.


Hazard raster addition: five 3320 x 1680 transparent categorical PNGs, 0.0025 degree overview cells (about 250 m). All 366 native cache grid dimensions verified against HydroBASINS bounding boxes projected using the four-corner EPSG:32645 convention; zero overlapping overview samples. National breaks and exact published RQ3 scheme inputs; RQ3 half-up class boundaries after ten-decimal score rounding. Missing native cells remain transparent. Five Python classification/artifact checks, 13 Vitest tests and five Chrome browser tests. Screenshot inspection confirms raster and district-outline alignment; mobile has no horizontal page overflow. Browser tests exercise all five raster URLs and both layer modes. These checks verify export mechanics and UI, not predictive accuracy of the research model.


Basin/navigation update (2026-10-31): 366 HydroBASINS L8/L9 research outlines; national and per-basin quintile rasters for all five schemes; explicit nearest-neighbor Web Mercator display variants. Added Leaflet pan, pinch/double-click/keyboard zoom, box zoom, fit-to-basin and fit-to-district, enlarged map, optional attributed Esri satellite tiles, and tile/vector/raster failure states. Classified overview resolution remains about 250 m. Exposure summary cards remain national-break results and do not become basin totals. Python checks independently compare Mercator rows to geographic samples, compare basin/national valid masks and class differences, and match basin IDs to cached units. Satellite browser tests use deterministic tiles; a separate Chrome check loaded actual provider tiles and inspected the real raster/imagery screenshot. Final checks: 13 Vitest tests, eight Python checks, eight Playwright browser tests; production build successful. No backend calls or mobile page overflow.
