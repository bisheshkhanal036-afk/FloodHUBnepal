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
