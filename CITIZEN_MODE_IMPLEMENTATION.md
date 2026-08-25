# Citizen Mode — What We Built

**Read this together with:** `CITIZEN_MODE_PLAN.md` (the design plan we
agreed before building anything) and `VALIDATION_PROCESS.md` (how the
profile this mode runs was chosen). This file documents what actually
got built, file by file, and what was tested. Nothing here has been
committed to git yet — this is the read-before-you-decide document.

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
