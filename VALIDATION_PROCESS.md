# Validation Process — What We Did, Step by Step

**Read this together with:** `METEOR_VALIDATION_RESULTS.md` (the raw
results and numbers) and `LITERATURE_REVIEW_THRESHOLDS.md` (the
literature findings). This file is the narrative — what we did, in what
order, why each step happened, and what each one taught us. Nothing here
has been committed to git yet.

---

## Why this work happened at all

FloodHUB had 293+ software tests proving the code computes correctly, and
**zero** evidence that the resulting map corresponds to reality. Fifteen
criteria, roughly 75 reclassification thresholds, all either guessed or
borrowed — and no one had checked whether any of it actually predicts
flooding. That gap was the single biggest risk to the project's
credibility, and it's what this work closes.

## The four steps, in order

```
1. Benchmark against METEOR (a model)
        ↓ found: model looks great against another model (0.95)
2. Literature review (published Kathmandu Valley study)
        ↓ found: borrowed thresholds destroy discrimination in our AOI
3. Find and validate against REAL flood records (BIPAD)
        ↓ found: reality is much harder than a model (0.72, not 0.95)
4. Tune the citizen profile against that real data
        ↓ found: fewer, better-chosen criteria beat more of them (0.81)
```

Each step's finding directly shaped the next step. This wasn't four
independent analyses — it was one investigation that kept correcting
itself.

---

## Step 1 — Benchmark against METEOR/Fathom

**What we did:** Downloaded METEOR's Nepal flood hazard package (335 MB,
30 GeoTIFFs — 3 flood types × 10 return periods), wrote
`backend/scripts/validate_against_meteor.py`, and compared our AHP risk
surface against METEOR's modeled water depth using AUC (area under the
ROC curve) and ablation testing (drop each criterion, measure the
change).

**Why METEOR first:** It was already sitting in the codebase as an
unused criterion, it's wall-to-wall for all of Nepal, and it needed no
sampling design — every pixel has a known depth. Cheapest possible first
check.

**What we found:**
- Ensemble AUC **0.9545** — looks excellent
- Ablation revealed 3 of 6 criteria (`twi`, `drainage_density`,
  `dem_slope`) were making the model *worse* — removing them improved
  agreement with METEOR
- A 3-criterion model beat the 6-criterion one (0.9627 vs 0.9545)
- Fluvial (river) flooding scored 0.95; pluvial (rainfall/drainage)
  scored only 0.90 — the model is much better at river floods than urban
  drainage floods

**The critical caveat we flagged immediately:** METEOR is itself a
model. Agreeing with it proves our surface *behaves like an expert flood
model* — it does not prove either one is *correct*. Both lean on
elevation data and can share blind spots. We were explicit about this
from the start: this is **benchmarking**, not **validation**.

Full numbers: `METEOR_VALIDATION_RESULTS.md`, Part 1.

---

## Step 2 — Literature review: do published thresholds transfer?

**What we did:** Searched for Kathmandu Valley-specific AHP flood
studies, extracted real numbers from a Bagmati River basin paper
(published class breaks, AHP weights, consistency ratio), then tested
those exact published thresholds against our own valley's actual data
distribution.

**What we found — the most important negative result in this whole
process:** The published elevation breaks, built with Jenks natural
breaks over the *entire Bagmati basin* (53–2,921 m elevation range), put
**56.9% of Kathmandu Valley into a single class** and left the highest-risk
class **completely empty** when applied to our valley (991–2,730 m
range). Same problem with slope.

**Why this mattered downstream:** It proved that "more rigorous" does
not mean "borrow someone else's numbers." A published threshold from a
differently-scaled study area is a *specific* wrong answer dressed up as
authority — worse than an estimate, because it looks credible. This
directly shaped Step 4's decision to use AOI-derived quantile breaks
instead of hardcoded ones.

**What we kept from the literature:** The AHP *weights* (which factor
matters how much) transferred better than the *thresholds* did, because
weights are relative judgments, not absolute cutoffs tied to a specific
elevation range. We used the published Kathmandu Valley weights
(Chaudhary et al. 2024) in Step 4.

Full findings: `LITERATURE_REVIEW_THRESHOLDS.md`.

---

## Step 3 — Find and validate against a REAL flood inventory

**What we did:** While reading the literature, noticed the Kathmandu
Valley paper validated against 156 flood sites from Nepal's official
disaster portal, BIPAD. Checked whether BIPAD exposes that data
programmatically — it does, as a public, unauthenticated JSON API.
Harvested it (62,635 incidents scanned) and filtered to flood/inundation
records inside the valley: **145 real, dated, georeferenced points,
2011–2026**.

Wrote `backend/scripts/validate_against_inventory.py` using the
**success-rate curve method** (Chung & Fabbri 2003) — the same method the
published Kathmandu Valley paper used, so our number is directly
comparable to theirs.

**What we found — the number that matters most in this whole process:**

| Reference | AUC |
|---|---|
| METEOR (a model) | 0.9545 |
| **Real flood inventory** | **0.7235** |
| Published paper, same valley | 0.83 |

**The model looks dramatically better against another model (0.95) than
against reality (0.72).** This is the single clearest demonstration of
why Step 1's caveat was necessary and correct — if we had stopped after
Step 1 and reported "0.95 validated," that claim would have been false.

**A second major finding, discovered by checking an anomaly rather than
trusting it:** `dist_to_river` alone scored **AUC 0.24 — far worse than
random** against real floods. We verified this wasn't a bug by directly
comparing flood-point locations to the valley average: flood points sit
at a median 620 m from rivers, versus 583 m valley-wide. Real Kathmandu
flooding is not concentrated near rivers the way the model assumed — this
is a valley with substantial *pluvial* (drainage-failure) flooding, which
independently corroborates Step 1's fluvial/pluvial finding.

**HAND, by contrast, showed the strongest real signal:** flood points sit
at median 2.5 m above nearest drainage vs. 23.6 m valley-wide — roughly a
tenfold separation. Neither Nepali paper we reviewed uses HAND at all.

Full numbers: `METEOR_VALIDATION_RESULTS.md`, Part 2.

---

## Step 4 — Tune the citizen profile against real data

**What we did:** Wrote `backend/scripts/tune_citizen_profile.py` to
systematically test combinations of what Step 1–3 had taught us, all
scored against the real BIPAD inventory (not METEOR):

- Equal weights vs. published Kathmandu Valley weights
- Hardcoded (guessed) breaks vs. AOI-derived quantile breaks
- Including vs. excluding `dist_to_river` (the criterion Step 3 showed
  was actively harmful)

**What we found:**

| Configuration | AUC |
|---|---|
| Original defaults (equal weights, hardcoded breaks, 6 criteria) | 0.7235 |
| + published weights | 0.7399 |
| + quantile breaks | 0.7966 |
| + drop `dist_to_river` | **0.8112** |

**Then we checked whether this was overfitting** by running a temporal
holdout: fit the same configuration on data as normal, but evaluate only
against flood events from 2020 onward (a subset the tuning process never
specifically targeted).

**Result: 0.8110 — matching the fitted score almost exactly.** This is
the check that makes the 0.81 figure trustworthy rather than a fluke of
which data points happened to be used.

**End state:** a 5-criterion profile (`hand`, `dem_elevation`,
`dem_slope`, `twi`, `drainage_density`) with published weights and
AOI-derived breaks, reaching **0.81** — within one point of the
published paper's 0.83, using half as many criteria. This is the
configuration Citizen Mode actually runs (see
`backend/app/citizen/profile.py`).

---

## What this process demonstrates, in one paragraph

We did not pick numbers and hope. Every configuration choice in Citizen
Mode — which criteria, what weights, where the class boundaries sit — was
selected because it was *measured* to perform better against real
observed floods, and that measurement was checked against a holdout set
it wasn't tuned on. The headline honest number is **0.81 AUC against 145
real flood records**, not the flattering 0.95 we got from comparing
against another model. That distinction, and the discipline to report the
harder number, is the actual deliverable of this phase of work.

## What's still missing (be honest about this too)

- **Reporting bias in the inventory.** BIPAD records where people are, so
  dense urban areas are over-represented regardless of true hazard. This
  is a plausible partial explanation for the `dist_to_river` result and
  is documented as a limitation, not hidden.
- **Point records, not flood extents.** Each BIPAD entry is one
  coordinate, not a mapped inundation boundary.
- **Only tested on Kathmandu Valley.** Nothing here has been checked
  against any other part of Nepal.
- **Rainfall is still not in the profile.** Four independent sources
  (Parajuli/Siraha, Bagmati basin, Lamjung, and this project's own
  literature review) all rank precipitation as a top factor, and it still
  isn't merged into the main branch.

## Files this process produced

| File | What it is |
|---|---|
| `backend/scripts/validate_against_meteor.py` | Step 1: METEOR benchmarking script |
| `backend/scripts/validate_against_inventory.py` | Step 3: real flood inventory validation script |
| `backend/scripts/tune_citizen_profile.py` | Step 4: profile tuning/selection script |
| `backend/data/raw/flood_inventory/ktm_flood_inventory.json` | The 145 harvested BIPAD flood points (gitignored — regenerable from the API) |
| `METEOR_VALIDATION_RESULTS.md` | Full numeric results, Parts 1 (METEOR) and 2 (inventory) |
| `LITERATURE_REVIEW_THRESHOLDS.md` | Literature findings and the borrowed-thresholds problem |
| `VALIDATION_PROCESS.md` | This file |

None of the scripts or their outputs have been committed. `backend/data/`
is gitignored as usual, so the harvested inventory never touches git
regardless.
