# Citizen Mode — What We Built

**Read this together with:** `CITIZEN_MODE_PLAN.md` (the design plan we
agreed before building anything) and `VALIDATION_PROCESS.md` /
`METEOR_VALIDATION_RESULTS.md` / `LITERATURE_REVIEW_THRESHOLDS.md` (the
full validation numbers). This file documents what actually got built,
file by file, what evidence it's built on, and what was tested.

---

## One-paragraph summary

Citizen Mode is a second, separate front door into FloodHUB: instead of
drawing an area and configuring 15 criteria and an AHP matrix, a person
taps one point on a map of Kathmandu Valley and gets one plain-language
answer — LOW / MODERATE / HIGH flood susceptibility, in English or
Nepali, with 2–3 reasons and a mandatory disclaimer. It reuses the
existing overlay engine entirely; nothing about the researcher tool
changed. The configuration it runs (which criteria, what weights, where
the risk boundaries sit) was chosen by measurement against real flood
data, documented in `VALIDATION_PROCESS.md`, not by guessing.

---

## What "citizen mode" actually means here — and doesn't

Agreed explicitly before building anything (see `CITIZEN_MODE_PLAN.md`
§2):

**It IS:** an awareness tool. "Does this place have a history of
flooding?" — useful for someone deciding where to live or what land to
buy.

**It is NOT:** a live flood warning, a forecast, an evacuation router, or
anything aware of flooding currently in progress. The backend has no
real-time data source at all. Every screen says this in plain language,
not a footnote.

---

## The evidence base: literature, AHP weights, and the flood inventory

Citizen Mode's configuration isn't invented — every number in
`profile.py` traces back to a specific published source or a specific
dataset we harvested ourselves. This section is that trail in full,
since it's the part most worth scrutinising before trusting the tool.

### Literature reviewed

Three papers, found by searching for Kathmandu Valley / Nepal AHP flood
studies:

1. **Chaudhary, U., Shah, M.A.R., Shakya, B.M., & Aryal, A. (2024).
   Flood Susceptibility and Risk Mapping of Kathmandu Valley Watershed,
   Nepal.** *Sustainability*, 16(16), 7101.
   https://doi.org/10.3390/su16167101 — **the single most relevant paper
   that exists for this project.** Same study area as ours, exactly.
   AHP with 10 conditioning factors, GIS, validated with AUC against 156
   historical flood sites from BIPAD. This is the paper that supplied
   both our AHP weights (below) and the idea of validating against
   BIPAD's own flood records.

2. **Flood vulnerability map of the Bagmati River basin, Nepal: a
   comparative approach of the analytical hierarchy process and
   frequency ratio model** (2024). *Smart Construction and Sustainable
   Cities*. https://doi.org/10.1007/s44268-024-00041-7 — Kathmandu
   Valley is the upstream sub-basin of this larger study area. Useful
   for cross-checking factor importance (precipitation weighted highest
   at 0.14 in their AHP), but its absolute class-break values turned out
   NOT to transfer to our smaller, higher, flatter valley — see below.

3. **Flood susceptibility mapping in a Himalayan mountain basin using
   GIS and multi-criteria analysis: a case study from Lamjung District,
   Nepal** (2026). *Arabian Journal of Geosciences*.
   https://doi.org/10.1007/s12517-026-12558-5 — nine factors at 10m
   resolution (matching our own grid resolution). AHP weighting found
   distance-to-river (0.156), rainfall (0.151), and TWI (0.152) as the
   dominant controls, CR = 0.037.

Full extraction detail, including every table we pulled numbers from:
`LITERATURE_REVIEW_THRESHOLDS.md`.

**The key negative finding, and why it matters for this profile
specifically:** we tested the Bagmati paper's published elevation class
breaks (Jenks natural breaks computed over their much larger, 53-2,921m
basin) directly against our valley's actual elevation distribution
(991-2,730m). The result: **56.9% of Kathmandu Valley fell into a single
"moderate" class, and the paper's own "very high" risk class (elevation
< 431m) was completely empty in our valley** — nothing here is that
low. Same failure mode with their slope breaks (50.8% in one class).

This is why `service.py`'s `_quantile_rules()` computes class breaks
from **this AOI's own data distribution** (quintiles) rather than using
any paper's absolute numbers. Borrowed thresholds built for a
differently-scaled study area don't just add noise — they can eliminate
a model's ability to discriminate at all inside the smaller area. The
weights transferred better than the thresholds did, because weights are
relative judgements between factors, not values pinned to a specific
elevation range.

### How the AHP weights were actually calculated

We did not run our own pairwise comparison survey. We used the
**published, already-computed** Kathmandu Valley weights from Chaudhary
et al. (2024), who did the full Saaty AHP procedure properly:

1. Built a 10x10 pairwise comparison matrix (their Table 3) — for every
   pair of factors, a domain expert judged relative importance on
   Saaty's 1-9 scale (1 = equal importance, 9 = extreme importance).
2. Normalized the matrix by dividing each cell by its column sum (their
   Table 4).
3. Averaged each row of the normalized matrix to get that factor's
   weight, expressed as a percentage.
4. Validated internal consistency via the Consistency Ratio:
   `CR = CI / RI`, where `CI = (lambda_max - n) / (n - 1)` (lambda_max =
   the matrix's principal eigenvalue, n = 10 factors) and `RI = 1.49` is
   Saaty's published Random Index value for a 10x10 matrix. **Their
   result: CR = 0.052**, well under the 0.10 threshold that AHP
   convention requires before weights are considered usable.

Their full weight table (Table 4 of the paper):

| Factor | Weight |
|---|---|
| Rainfall | 23% |
| Elevation | 22% |
| Slope | 16% |
| TWI | 10% |
| Distance from river | 8% |
| Curvature | 8% |
| LULC | 5% |
| Drainage density | 4% |
| Geology | 2% |
| Soil | 2% |

**What we did with this table:** Citizen Mode uses 5 of these 10
factors (`hand`, `dem_elevation`, `dem_slope`, `twi`,
`drainage_density` — chosen per the validation work in
`VALIDATION_PROCESS.md`, which found `dist_to_river` actively harmful
against real flood data). `hand` isn't in the published table at all —
it's substituted in at distance-from-river's weight (8%), since HAND
functionally replaces distance-to-river as this profile's
channel-proximity term. The five remaining weights are then
renormalized to sum to 1 (`profile.normalized_weights()`):

```
hand:              8  / 60 = 0.1333
dem_elevation:    22  / 60 = 0.3667
dem_slope:        16  / 60 = 0.2667
twi:              10  / 60 = 0.1667
drainage_density:  4  / 60 = 0.0667
```

This is a real, published, peer-reviewed AHP result for this exact study
area — not a guess and not our own subjective judgement — adapted only
by dropping the factors we don't have or measured to be unhelpful, and
rescaling what's left.

### The BIPAD flood inventory: what it is and how we got it

**BIPAD** (Built and Integrated Platform for Assessing and Dispatching)
is Nepal's official disaster information platform, operated by the
**National Disaster Risk Reduction and Management Authority (NDRRMA)**,
Government of Nepal — the same portal Chaudhary et al. (2024) used to
validate their own model (they collected 156 flood sites from it plus
newspaper/unpublished reports).

We discovered BIPAD exposes a **public, unauthenticated JSON REST API**:

```
https://bipadportal.gov.np/api/v1/incident/?hazard=<id>&limit=<n>&offset=<n>
```

Each incident record includes a point geometry (`{"type": "Point",
"coordinates": [lon, lat]}`), a title (English and Nepali), the incident
date (`incidentOn`), verification/approval flags, and a `hazard` field
that's an integer code. We queried `/api/v1/hazard/` to get the code
table and confirmed:

```
hazard = 11   ->  Flood
hazard = 28   ->  Inundation
```

(Other codes exist for landslide, fire, earthquake, and 40+ other
hazard types — we only kept these two.)

**Harvest process:** paginated through the full incident endpoint
(500 records per page), scanning **62,635 incidents** of every hazard
type nationwide, keeping only records where `hazard` was Flood or
Inundation **and** the point fell inside a generous Kathmandu Valley
bounding box (85.15-85.60 deg E, 27.55-27.90 deg N). Result: **145
flood/inundation points, dated 2011-2026**, saved to
`backend/data/raw/flood_inventory/ktm_flood_inventory.json`.

This file is **gitignored** like everything under `backend/data/` — it
is regenerable from the public API at any time and was never intended
to be a static, versioned artifact.

**How it was actually used:** `validate_against_inventory.py` samples
our risk surface's value at each of these 145 real point locations and
runs the **success-rate curve** method (Chung & Fabbri 2003 — the
standard for exactly this kind of point-inventory validation, and the
same method Chaudhary et al. used, which is what makes our AUC directly
comparable to their reported 0.83). The method: rank every pixel in the
study area by predicted risk, sweep the threshold from highest-risk
down, and plot what fraction of the 145 real flood points are captured
against what fraction of the total area you'd have to flag to catch
them. AUC of that curve is the headline number — **0.7235** for the
original 6-criterion equal-weighted model, rising to **0.8112** for the
tuned 5-criterion profile Citizen Mode actually runs, holding at
**0.8110** on a temporal holdout using only events from 2020 onward
(proving the number isn't just fit to whichever points happened to be
in the training set).

**Known limitations of this inventory, stated plainly:**
- **Reporting bias** — incidents get recorded where people live and
  report them, so dense urban wards are structurally over-represented
  relative to sparsely populated areas, regardless of true physical
  hazard.
- **Point locations, not flood extents** — each record is one
  coordinate (often a ward or settlement centroid), not a mapped
  inundation boundary.
- **Recency bias** — BIPAD's own data collection has grown substantially
  more complete since roughly 2011; earlier events are under-represented.

---

## New files, and what each one does

### Backend — `backend/app/citizen/`

| File | Job |
|---|---|
| `__init__.py` | Package entry, exports the router |
| `profile.py` | **The fixed, validated configuration** — which 5 criteria, what weights, class-to-label mapping, the measured accuracy numbers. This is the file that encodes everything Step 4 of `VALIDATION_PROCESS.md` found. |
| `service.py` | The actual pipeline: computes one shared valley-wide surface, samples it at a point, builds plain-language reasons from the same classification that produced the score |
| `models.py` | Request/response shapes **and all bilingual text** — every English/Nepali string a citizen sees, including the disclaimer |
| `router.py` | Two endpoints: `POST /api/citizen/assess` and `GET /api/citizen/coverage` |

### Backend — validation scripts (see `VALIDATION_PROCESS.md` for detail)

`backend/scripts/validate_against_meteor.py`,
`validate_against_inventory.py`, `tune_citizen_profile.py` — these
produced the numbers `profile.py` encodes. Not part of the running
application; developer tools run manually.

### Frontend

| File | Job |
|---|---|
| `frontend/src/components/ModeSelect.jsx` | The fork screen: "Check my area" vs "Build a model" |
| `frontend/src/components/CitizenView.jsx` | The whole citizen experience — its own map, its own state, bilingual UI |
| `frontend/src/api/client.js` (modified) | Added `assessLocation()` and `fetchCitizenCoverage()` |
| `frontend/src/App.jsx` (modified) | Added `modes` and `citizen` to the view state machine |
| `frontend/src/index.css` (modified) | Citizen Mode styling, reusing existing design tokens |
| `backend/app/main.py` (modified) | One line: registers the citizen router |

**Nothing in `frontend/src/components/Sidebar.jsx`, `MapView.jsx`,
`AppStateContext.jsx`, or any researcher-tool file was touched.** Citizen
Mode is additive.

---

## How a request actually flows

```
User taps the map (or grants location permission)
        │
        ▼
POST /api/citizen/assess { lat, lon, lang }
        │
        ▼
router.py → service.assess(lon, lat)
        │
        ├─ Outside Kathmandu Valley pilot box? → honest "not covered yet"
        │
        ▼
service.get_pilot_surface()
   — ONE shared risk surface for the whole valley, computed once,
     cached. See "why one shared surface" below.
        │
        ▼
Sample the surface at this exact pixel
        │
        ▼
_build_reasons() — reads the SAME per-criterion classification
   that produced the score, ranks by actual contribution
        │
        ▼
models.py wraps it in bilingual text + disclaimer + validation numbers
        │
        ▼
JSON response → CitizenView renders the answer
```

---

## Three design decisions worth understanding, not just accepting

### 1. Why one shared valley surface, not a box per user

`AOI.cache_key()` hashes the bounding box to 8 decimal places. If every
user got a small box centered on their own tap, every single request
would have a unique key and miss the cache — a ~60-second wait, every
time, for everyone. Instead, Citizen Mode computes **one surface for the
whole valley**, once, and every point-check after that is a cache read
(well under a second). This also gives HAND and TWI — both derived from
flow routing — a proper full-valley catchment instead of being clipped
at an arbitrary small box edge, which the project's own SPEC.md already
documents as a source of error.

### 2. Why reasons are derived from the classification, not raw thresholds

**A real bug we caught by testing, not by review.** The first version
generated reasons from hand-picked absolute cutoffs (e.g., "HAND below
5 m"). Testing a real location (Sinamangal) returned a HIGH risk score
with **zero reasons attached** — because the score comes from
quintile-based classification relative to the whole valley, while the
reason rules were testing unrelated fixed numbers. The fix: reasons are
now derived from the same per-criterion classification (1–5) that
produced the score, ranked by each criterion's actual weighted
contribution. They can no longer disagree with the number they're
explaining. Documented in `service.py`'s comments so it doesn't regress.

### 3. Why text lives in the backend, not the frontend

Every risk label, reason, and — critically — the disclaimer is generated
server-side in both languages and shipped as part of the API response.
This means no client can ever render a risk level without the caveat
that qualifies it traveling alongside it. It's a deliberate constraint,
not a convenience.

---

## Testing performed

**Backend:**
- Existing regression suite (`tests/overlay`, `tests/common`,
  `tests/districts`, `tests/basins`, `tests/test_ahp_core.py`) —
  **207 passed**, confirming Citizen Mode's addition broke nothing in the
  researcher tool
- Manual endpoint testing via curl/PowerShell across multiple real
  locations:

  | Location | Result | Sanity check |
  |---|---|---|
  | Sinamangal (low-lying, near Bagmati) | HIGH (0.825) | Known flood-prone area — correct |
  | Shivapuri hills (high ground, north) | LOW (0.167) | Hillside, should be safe — correct |
  | Bhaktapur Durbar Square | HIGH (0.708) | Flat, low-lying urban core — plausible |
  | Pokhara (outside the pilot area) | "not covered" | Correctly refused rather than guessing |

- Confirmed Nepali-language responses render correctly, including the
  full disclaimer
- Confirmed warm-cache response time: ~2 seconds (includes network +
  reprojection), vs. the ~60-second first-computation cost

**Frontend — live browser test (Chrome, via automation), not just code
review:**
- Landing page → mode select → Citizen Mode: all render correctly
- Kathmandu Valley map loads with the pilot-area boundary shown
- Tapping a real location (Baneshwor) returned HIGH with 3 reasons, the
  accuracy disclosure, and the full disclaimer, matching what the API
  test showed
- Nepali toggle switches all UI text and the live result correctly
- Checked the browser console: **no errors**

---

## What is genuinely new here vs. what is reused

**Reused, unmodified:** the AHP compute engine, the reclassification
system, the criterion source registry (`hand`, `dem_elevation`,
`dem_slope`, `twi`, `drainage_density` — all already existed), the
caching layer, MapLibre GL for the map.

**New:** the fixed-profile decision layer, the point-sampling logic, the
plain-language reason generation, the bilingual text system, and the
two-mode entry UI. Citizen Mode adds no new data sources and no new
compute method — it's a different way of asking the existing engine a
narrower question, with an answer format built for a different audience.

---

## What is explicitly NOT done yet

- **Nightly precompute job.** The valley surface caches after first
  computation but nothing refreshes it on a schedule. Right now the first
  request each cache-invalidation cycle pays the ~60s cost.
- **Cache retention policy.** `CITIZEN_MODE_PLAN.md` flagged this; not
  implemented.
- **Rainfall in the profile.** Still not merged into the criteria set,
  despite four independent sources ranking it as a top factor.
- **Anything beyond Kathmandu Valley.** Hard-coded pilot boundary,
  deliberately.
- **Committed to git.** Everything described here exists only in the
  working tree.

---

## Files touched, for the record

```
NEW
  backend/app/citizen/__init__.py
  backend/app/citizen/profile.py
  backend/app/citizen/service.py
  backend/app/citizen/models.py
  backend/app/citizen/router.py
  backend/scripts/validate_against_meteor.py
  backend/scripts/validate_against_inventory.py
  backend/scripts/tune_citizen_profile.py
  frontend/src/components/CitizenView.jsx
  frontend/src/components/ModeSelect.jsx

MODIFIED
  backend/app/main.py           (+2 lines: register citizen router)
  frontend/src/App.jsx          (view state machine: landing/modes/citizen/tool)
  frontend/src/api/client.js    (+2 functions: assessLocation, fetchCitizenCoverage)
  frontend/src/index.css        (+ Citizen Mode styles, appended)

UNTOUCHED
  Every researcher-tool component, AppStateContext, and existing route.
```
