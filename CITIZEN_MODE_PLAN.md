# Citizen Mode — Design Plan

**Status:** proposal for team discussion. Nothing built yet.
**Author:** Anuj Thapa
**Date:** 2026-08-24

---

## 1. The problem

FloodHUB is currently a tool for people who already understand flood
modelling. To get an answer, a user must:

1. Draw a bounding box or pick a HydroBASINS basin
2. Choose which of 13 conditioning criteria to enable
3. Choose a weighting method — equal, manual, or AHP pairwise
4. If AHP: fill a 5×5 cluster matrix plus per-cluster matrices on
   Saaty's 1–9 scale, and keep the Consistency Ratio below 0.10
5. Optionally tune 5-class reclassification breaks per criterion
6. Press Compute and read a continuous risk surface

That is the correct interface **for a researcher**. It is an impossible
interface for a resident of Kathmandu who wants to know whether their
neighbourhood floods.

The underlying model is genuinely useful to that person. The interface is
the only thing standing between them and it.

## 2. What Citizen Mode is — and is not

This is the most important section. Get it wrong and the feature becomes
dangerous rather than useful.

### It IS

> **An awareness tool.** "Does the area I live in tend to flood, and has
> it been raining heavily here lately?"

### It is NOT

- ❌ A live flood warning
- ❌ A forecast
- ❌ An evacuation router ("go this way, now")
- ❌ Aware of any flooding currently in progress

### Why the distinction is non-negotiable

The backend has **no real-time data, no shelters, and no routing**.
Verified by grep across the whole codebase: zero hits for forecast,
alert, discharge, or water level.

If we present a static susceptibility model inside an emergency-styled
UI, a frightened person at 2 a.m. will trust it as live guidance. Flood
fatalities frequently occur to people *evacuating* along a route they
believed was safe. A researcher reads a susceptibility map with
appropriate scepticism; a scared resident will not.

**Design rule:** every screen in Citizen Mode states what the data is and
is not, in plain language, where it is actually read — not in a footer.

## 3. Performance: measured, with the agreed citizen profile

Criteria: `hand`, `dist_to_river`, `dem_slope`, `recent_rainfall`, `twi`.
Equal weights. Measured on the dev machine, Kathmandu Valley.

| Area | Cold | Warm | Memory |
|---|---|---|---|
| 100 km² (5 km radius, one user) | 9.7 s | **0.36 s** | 335 MB |
| 725 km² (whole valley, one surface) | 63.5 s | **0.87 s** | 422 MB |

(The 17–32 s figures seen elsewhere are `GET /api/basins` loading a
300 MB HydroBASINS shapefile — not compute.)

Processed cache on disk after these runs: **1.2 GB**.

### The cache-key problem, and why it decides the architecture

`AOI.cache_key()` is `sha256(bbox rounded to 8 decimal places)`.

That means **any** difference in a user's tapped coordinates produces a
different bbox, a different key, and a total cache miss. If each user got
a 5 km box centred on their own tap, essentially every request would be a
cold ~10 s compute. Pre-computation would be worthless.

Two ways out:

| Option | How | Verdict |
|---|---|---|
| **Snap taps to a fixed grid** | Quantise the tap to e.g. a 0.02° grid, build the box around the snapped centre | Works, but needs ~260 overlapping pre-computes for the valley and puts edge-users off-centre |
| **One valley-wide surface** ✅ | Pre-compute the whole valley once; sample each user's point out of it | 1 pre-compute instead of 260, no snapping, no edge artefacts |

**Recommendation: the valley-wide surface.** It is simpler, cheaper, and
*more accurate* — HAND and TWI both derive from flow routing, and SPEC.md
already documents that flow accumulation is unreliable near a bbox edge.
A valley-wide catchment gives those two criteria far better context than
a 10 km box would.

## 4. Architecture

```
  ┌─────────────────────────────────────────────┐
  │  Landing page                               │
  │  ┌───────────────────┐ ┌──────────────────┐ │
  │  │  Check my area    │ │  Build a model   │ │
  │  │  (citizen)        │ │  (researcher)    │ │
  │  └─────────┬─────────┘ └────────┬─────────┘ │
  └────────────┼────────────────────┼───────────┘
               │                    │
               ▼                    ▼
   ┌───────────────────────┐   existing tool,
   │ 1. Set your location  │   UNCHANGED
   │    · tap the map      │
   │    · or use my        │
   │      location (opt-in)│
   └───────────┬───────────┘
               ▼
   ┌───────────────────────────────────────┐
   │ 2. POST /api/citizen/assess           │
   │    { lat, lon }                       │
   │    → fixed criteria, equal weights    │
   │    → samples the pre-computed         │
   │      valley-wide surface at the point │
   │    → milliseconds (no compute)        │
   └───────────┬───────────────────────────┘
               ▼
   ┌───────────────────────────────────────┐
   │ 3. Plain-language answer              │
   │    HIGH / MODERATE / LOW              │
   │    + 2–3 reasons in plain words       │
   │    + what this is and isn't           │
   │    + where to get live information    │
   └───────────────────────────────────────┘
```

### Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Area selection | **Point sampled from a pre-computed valley-wide surface** | No drawing, no basins, no per-user AOI. Avoids the cache-key problem entirely (§3) and gives HAND/TWI a proper catchment. |
| Criteria | **Fixed set, not user-chosen** | The choice is a modelling decision; making it is our job, not theirs. |
| Weights | **Equal, frozen** | Agreed for v1. No AHP, no CR, no matrices. Revisit once validated. |
| Location capture | **Tap-to-place first, geolocation opt-in second** | Tap works when permission is denied, GPS is poor indoors, or checking on family elsewhere. Geolocation is a convenience on top, not the only path. |
| Output | **One word + reasons** | Not a continuous [0,1] surface. Not a GeoTIFF. |

### On location privacy

Browser geolocation is **not** a privacy violation: it requires explicit
user permission through the browser's own consent prompt. It does need
HTTPS in production (localhost is exempt, so dev is unaffected).
Tap-to-place is built first regardless, so the feature never *depends* on
that permission being granted.

## 5. Backend work required

### 5.1 New endpoint: `POST /api/citizen/assess`

The one genuine gap. There is currently no way to ask "what is the risk
*at this point*" — every endpoint returns a whole surface.

```
Request:  { "lat": 27.7041, "lon": 85.3240 }

Response: {
  "risk_level": "high",              // low | moderate | high
  "hazard_class": 4,                 // 1-5, from the existing raster
  "reasons": [
    { "code": "low_lying",     "text": "Low-lying ground near the valley floor" },
    { "code": "near_river",    "text": "About 180 m from the nearest river" },
    { "code": "recent_rain",   "text": "About 75 mm of rain in the last 7 days" }
  ],
  "data_currency": {
    "rainfall_date": "2026-08-20",
    "days_stale": 4
  },
  "disclaimer": "...",
  "cache_key": "..."                 // so the map can show the surface
}
```

**Implementation:** looks up today's pre-computed valley surface, samples
the hazard-class raster at the requested point, and derives `reasons`
from the per-criterion rasters already written for that same surface. No
new modelling and, on the happy path, **no compute at all** — a thin
read-and-present layer over machinery that already exists.

If the point falls outside any pre-computed region, respond honestly
("this area isn't covered yet") rather than silently computing for 60 s.

### 5.2 Reason generation

The "why" is what makes the answer trustworthy and actionable. Each
reason is derived from a criterion's raw value at the point, thresholded
into plain language:

| Criterion | Triggers a reason when | Plain text |
|---|---|---|
| `hand` | < 5 m above nearest drainage | "Only Xm above the nearest river channel" |
| `dist_to_river` | < 500 m | "About Xm from the nearest river" |
| `dem_slope` | < 3° | "Very flat ground — water drains slowly" |
| `recent_rainfall` | > 50 mm/7 days | "About Xmm of rain in the last 7 days" |
| `twi` | high | "Terrain here collects water from upslope" |

Only the top 2–3 firing reasons are shown. Ordered by contribution.

### 5.3 Nightly pre-computation job

`recent_rainfall` re-caches daily by design (its cache key includes the
date), so the surface must be rebuilt daily too.

**Coverage unit: the basin polygon, not a bbox.** `HYBAS_ID 4080848980`
(HydroBASINS level 8, 1,333 km²) contains central Kathmandu and *is* the
valley's watershed. Polygon AOIs are already exempt from the 1,000 km²
cap, so this needs **no change to `MAX_AREA_KM2`** — a shared guard that
protects every other endpoint and user.

Rejected alternatives:

| Option | Why not |
|---|---|
| Raise `MAX_AREA_KM2` | Weakens a shared safety limit for every endpoint and user, to solve a problem local to one feature. |
| Split into 2 bbox tiles | HAND and TWI are flow-routing derived and SPEC.md documents bbox-edge unreliability. An arbitrary seam would run that unreliability straight through the most densely populated part of the valley. |

A basin boundary is a **watershed divide** — flow does not cross it by
definition — so if coverage ever needs several basins, those seams are
hydrologically correct rather than artefacts.

**Measured cost (basin AOI, 5 criteria, polygon-masked):**

| | Value |
|---|---|
| Cold compute (the nightly job) | **305 s** |
| Peak memory | 506 MB |
| Risk-surface GeoTIFF | 106 MB |
| Processed-cache pickle | 239 MB |
| **Point sample from the result** | **0.19 s** |

The job is slower than a plain bbox of similar useful area because the
grid is built on the basin's *bounding box* (2,588 km²), 1.9× the
polygon's own 1,333 km². Accepted: it is a batch job, nobody waits on it.

**Point sampling is the number that matters for users** — 0.19 s, and
independent of surface size, since rasterio reads a single-pixel window.

**New requirement: cache retention.** ~345 MB is written per day and the
daily rainfall key means it never self-replaces. Needs a cleanup policy
(proposal: keep the last 2–3 days, delete older) or the disk fills.

**Fallback on a cache miss** (job failed, or CHIRPS was late): serve the
most recent surface available and say how old it is — the honesty
machinery already exists for exactly this. Never silently block a user
for 5 minutes.

## 6. Frontend work required

New components, none replacing anything existing:

| Component | Job |
|---|---|
| `ModeSelect.jsx` | The two-way entry choice on the landing page |
| `CitizenView.jsx` | Container — replaces `Sidebar`+`MapView` layout in this mode |
| `LocationPicker.jsx` | Tap-to-place, plus opt-in "use my location" |
| `RiskAnswer.jsx` | The big plain-language result + reasons |
| `DataHonesty.jsx` | What this is / isn't + links to DHM, BIPAD |

`App.jsx` changes from `view: 'landing' | 'tool'` to
`view: 'landing' | 'citizen' | 'tool'`. `AppStateProvider` continues to
wrap all views. **The researcher path is untouched.**

### What a citizen actually sees

```
┌────────────────────────────────────────┐
│  Your area                             │
│                                        │
│         ████  HIGH  ████               │
│      flood susceptibility              │
│                                        │
│  Why:                                  │
│   • Low-lying ground near the valley   │
│     floor                              │
│   • About 180 m from the Bagmati       │
│   • About 75 mm of rain fell here in   │
│     the last 7 days                    │
│                                        │
│  ────────────────────────────────────  │
│  ⓘ  This shows which areas TEND to     │
│     flood, based on terrain, rainfall  │
│     patterns and drainage.             │
│     It is NOT a live warning and does  │
│     not know current conditions.       │
│                                        │
│     Rainfall data: 20 Aug (4 days old) │
│                                        │
│     For current alerts:                │
│     · DHM — hydrology.gov.np           │
│     · BIPAD — bipadportal.gov.np       │
└────────────────────────────────────────┘
```

## 7. Deliberately out of scope

Named explicitly so nobody expects them:

| Not building | Why |
|---|---|
| Evacuation routes | No routing engine, no shelter data. Would be inventing guidance we cannot stand behind. |
| Shelter markers | No shelter dataset exists. `main.py` still says shelter logic is unimplemented. |
| Live alerts / push notifications | No real-time data source. Requires DHM gauge feeds — an institutional access problem, not a code problem. |
| "You are in danger" language | The model cannot know this. |

**Phase 2 (later, honestly framed):** once shelters and routing exist,
frame it as *"plan your route before flood season"* — pre-flood planning,
not live navigation. That is what the reference paper (Parajuli et al.,
2023) actually did.

## 8. Phasing and effort

| Phase | Scope | Estimate |
|---|---|---|
| **0** | This document — team agreement on scope and honesty rules | done |
| **1a** | `POST /api/citizen/assess` + reason generation + tests | 1–2 days |
| **1b** | `ModeSelect` + `LocationPicker` + `RiskAnswer` + `DataHonesty` | 2–3 days |
| **1c** | Nightly pre-compute job for Kathmandu Valley | 1 day |
| **2** | Nepali language; offline/low-bandwidth mode | 2–3 days |
| **3** | Shelters + flood-aware routing (separate project, needs data) | weeks |

Phase 1 total: **4–6 days** for a working, honest Citizen Mode.

## 9. Decisions taken

| # | Question | Decision |
|---|---|---|
| 1 | Citizen criteria profile | `hand`, `dist_to_river`, `dem_slope`, `recent_rainfall`, `twi` — hazard only. Excludes building/population density (exposure, not hazard; the buildings extract also OOMs the container today). |
| 2 | Weights | **Equal**, frozen for v1. |
| 3 | Neighbourhood scale | **5 km** radius — measured viable (9.7 s cold / 0.36 s warm). Superseded in practice by the valley-wide surface (§3), which serves the same points more cheaply; 5 km remains the fallback shape for any area outside a pre-computed region. |
| 5 | Pre-compute coverage | **Kathmandu Valley first**, then expand. |
| 6 | Show a map? | **Yes** — but a reduced one: centred on the user's point, three colours, no layer controls, no legend beyond the risk level. Enough to confirm "that's my neighbourhood", not enough to invite analysis. |

### Still open

**4. Hazard class → risk level.** **Agreed.** Mapping:

| Hazard class | Citizen label |
|---|---|
| 1–2 | **LOW** |
| 3 | **MODERATE** |
| 4–5 | **HIGH** |

Three labels rather than five, because a citizen acts on "should I worry
about this" and five gradations invite false precision we have not
validated.

**7. Cap vs. full-valley coverage** — **decided**: use basin polygon
`HYBAS_ID 4080848980`, which is already cap-exempt. See §5.3.

**8. Cache retention policy** — new, surfaced by measurement. ~345 MB/day
accumulates. Proposal: keep the last 2–3 days.

## 10. Why this matters

BIPAD is the national authority and is better-resourced than us. We
should not try to beat it at being a government dashboard.

But BIPAD is a dense, heavy, English-first analyst portal. Nobody has
built the simple version: *tap where you live, get one honest sentence
about it.* That is a real, unserved gap, it is achievable in under a
week, and it does not require pretending to capabilities we do not have.
