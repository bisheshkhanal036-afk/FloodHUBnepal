# METEOR Benchmarking — Results

**Run:** 2026-08-25 · Kathmandu Valley (85.22–85.52 E, 27.60–27.82 N, ~725 km²)
**Reference:** METEOR Project Nepal flood hazard (Fathom framework), ~90 m
**Model under test:** 6-criterion AHP, equal weights, default UI reclassification rules
**Sample:** 7,079,904 valid pixels

> **What this is:** model-to-model benchmarking against an independent expert
> flood model. **Not** validation against observed floods. METEOR is itself a
> model; agreement means our surface behaves like an expert flood model, not
> that either is correct. Both lean on elevation data and can share blind
> spots. Real flood-inventory validation (Sentinel-1 SAR / Copernicus EMS)
> remains necessary and is not replaced by this.

---

## 1. Headline

| Metric | Value |
|---|---|
| **Ensemble AUC** (AHP surface vs METEOR floodplain, FD 1-in-100) | **0.9545** |
| Spearman ρ (risk score vs modelled depth) | +0.2423 |
| METEOR-flooded fraction (>0.15 m) | 2.31% |

An AUC of 0.95 is strong — comfortably above the ~0.8 typically reported as
"good" in the flood-susceptibility literature. The model reproduces an
independent hydraulic model's floodplain to a high degree.

**Why ρ is low while AUC is high, and why that is expected:** AUC asks
*"does risk rank flooded pixels above dry ones?"* — which the model does very
well. Spearman ρ asks *"does risk track depth continuously?"* — which it
cannot, because 97.7% of pixels have zero modelled depth, so the correlation
is dominated by ties. The AHP surface is a **susceptibility** model, not a
depth model. It was never designed to predict how deep the water gets, only
where it goes. The two numbers together say exactly that.

## 2. Class concordance

Mean AHP hazard class (1–5) within each METEOR depth band:

| METEOR depth band | Pixels | Mean AHP class |
|---|---|---|
| none/nuisance (<0.15 m) | 6,916,007 | **2.12** |
| moderate (0.15–0.5 m) | 42,639 | **4.18** |
| serious (0.5–1 m) | 36,174 | **4.25** |
| severe (1–2 m) | 38,347 | **4.26** |
| extreme (>2 m) | 46,737 | **4.32** |

The jump from 2.12 → 4.18 at the flooded boundary is sharp and correct.
But classes 4.18 → 4.32 across four depth bands is nearly flat: **the model
separates flooded from dry very well, and barely distinguishes severity at
all.** Same conclusion as the ρ/AUC split, from a different direction.

## 3. Per-criterion solo AUC

Each criterion alone, reclassified 1–5, unweighted:

| Criterion | Solo AUC |
|---|---|
| `dem_elevation` | **0.9060** |
| `hand` | **0.9041** |
| `dist_to_river` | 0.8877 |
| `dem_slope` | 0.8422 |
| `twi` | 0.7507 |
| `drainage_density` | 0.7132 |

**The finding that matters: `dem_elevation` alone scores 0.906. The full
6-criterion ensemble scores 0.954.** Five extra criteria buy +0.048 AUC over
a single criterion any GIS undergraduate could compute in one step.

## 4. Ablation — drop one criterion, recompute

| Dropped | AUC without | Δ |
|---|---|---|
| `dist_to_river` | 0.9340 | **−0.0206** |
| `hand` | 0.9381 | **−0.0164** |
| `dem_elevation` | 0.9419 | **−0.0126** |
| `dem_slope` | 0.9564 | **+0.0019** |
| `drainage_density` | 0.9572 | **+0.0026** |
| `twi` | 0.9578 | **+0.0033** |

**Three criteria actively hurt the model.** Removing `twi`,
`drainage_density`, or `dem_slope` makes agreement with METEOR *better*.

This is the multicollinearity problem made concrete: six DEM-derived criteria
compete for a fixed weight budget, and the weakest ones dilute the strongest.
`twi` and `drainage_density` have the lowest solo AUCs (0.75, 0.71) *and*
negative marginal value — they are consuming 1/6th of the weight each while
degrading the result.

**Confirmed by direct test** (`--only`, equal weights, same AOI/reference):

| Model | Criteria | AUC | vs 6-criterion |
|---|---|---|---|
| 2-criterion | `dist_to_river`, `hand` | 0.9475 | −0.0070 |
| **3-criterion** | **+ `dem_elevation`** | **0.9627** | **+0.0082** |
| 4-criterion | + `dem_slope` | 0.9615 | +0.0070 |
| 6-criterion (baseline) | + `twi`, `drainage_density` | 0.9545 | — |

**Half the criteria produce a better model.** The 3-criterion model beats the
6-criterion one by +0.0082 AUC. Adding `dem_slope` back makes it slightly
worse; adding `twi` and `drainage_density` makes it worse again.

Two is too few (0.9475) — `dem_elevation` carries real independent signal.
Three is the sweet spot.

## 5. Robustness across return periods

FD, ablation skipped:

| Return period | AUC | METEOR-flooded |
|---|---|---|
| 1-in-5 | 0.9582 | 0.76% |
| 1-in-20 | 0.9563 | 1.61% |
| 1-in-100 | 0.9545 | 2.31% |
| 1-in-500 | 0.9536 | 3.00% |
| 1-in-1000 | 0.9531 | 3.26% |

Remarkably stable (0.9531–0.9582 across a 200× range of event rarity). The
model is not tuned to one scenario — it captures the persistent geography of
where water goes, which is what a susceptibility model should do.

## 6. Flood type — the most scientifically important result

1-in-100, ablation skipped:

| Flood type | AUC | METEOR-flooded |
|---|---|---|
| Fluvial Defended | 0.9545 | 2.31% |
| Fluvial Undefended | 0.9543 | 2.32% |
| **Pluvial** | **0.9024** | **7.74%** |

Two things here:

**(a) Defended ≈ Undefended (0.9545 vs 0.9543).** METEOR's own defended and
undefended scenarios are nearly identical over the valley — meaning Kathmandu
Valley has little modelled flood-defence infrastructure to make a difference.
A real finding about the study area, not about our model.

**(b) Pluvial is markedly worse (0.90 vs 0.95), on 3.3× more flooded area.**
This is the model's honest weakness, and it makes physical sense:

- Fluvial (river) flooding is driven by distance-to-river, HAND and
  elevation — exactly what our top three criteria measure.
- Pluvial (rainfall-ponding) flooding happens *away from rivers*, driven by
  local depressions, soil infiltration and drainage capacity — which our
  criteria capture poorly.

**Our model is a good river-flood model and a weaker rainfall-flood model.**
For an urban valley like Kathmandu, where much real flooding is drainage
failure rather than river overflow, that gap matters and should be stated
plainly rather than hidden behind the headline 0.95.

---

## 7. What to do with this

1. **Prune to three criteria.** Done and confirmed: `dist_to_river`, `hand`,
   `dem_elevation` scores **0.9627** vs the 6-criterion 0.9545. A simpler
   model that performs *better* is strictly better. Propose this to the team.
2. **Stop adding criteria** until each new one demonstrates positive marginal
   AUC. The evidence now exists to require this.
3. **Promote METEOR out of the criteria list** into the permanent reference
   standard. Using it as an AHP input while benchmarking against it is
   circular; it was excluded from this study for exactly that reason.
4. **Target the pluvial gap.** `soil_infiltration` and the drainage-related
   criteria were not in this run — test whether they close it. This is the
   clearest place where a *new* criterion could earn its place.
5. **Report severity separately, or not at all.** The model ranks flood
   extent well and severity barely at all. The UI's 1–5 hazard classes imply
   a severity gradient the model does not support.
6. **Do the real thing eventually.** Sentinel-1 SAR or Copernicus EMS
   inventory validation for the 2024 Kathmandu floods. This benchmark is a
   strong interim result, not a substitute.

## Reproduce

```bash
docker cp backend/scripts/validate_against_meteor.py \
  floodhubnepal-main-backend-1:/app/validate_against_meteor.py
docker compose exec -T backend python /app/validate_against_meteor.py \
  --flood-type FD --return-period 1in100 \
  --out /app/data/cache/validation_meteor.json
```

Requires METEOR layers at `backend/data/raw/meteor_flood/{TYPE}_{RETURN}.tif`
(download: https://maps.meteor-project.org/map/flood-npl/download, 335 MB,
ODbL licensed).

---

# PART 2 — Validation against a REAL flood inventory

**Added 2026-08-25, after the METEOR work above.**

## 8. We found real ground truth

While reviewing Chaudhary et al. (2024) — the Kathmandu Valley AHP paper —
we noticed it validated against 156 historical flood sites from Nepal's
national disaster portal. That portal (**BIPAD**, NDRRMA) turns out to expose
a **public, unauthenticated JSON API** with georeferenced, dated incident
records:

```
https://bipadportal.gov.np/api/v1/incident/?hazard=11    # 11=Flood, 28=Inundation
```

Harvesting it (62,635 incidents scanned) yielded **145 flood/inundation
points inside the Kathmandu Valley, 2011–2026** — a genuine observed
inventory, comparable to the 156 the published paper used.

**This upgrades the claim from "benchmarked against a model" to "validated
against an observed flood inventory."**

Method: **success-rate curve** (Chung & Fabbri 2003) — rank all pixels by
susceptibility, sweep the threshold, plot cumulative % of flood points
captured against cumulative % of area. Needs no synthetic "non-flood"
samples, which is exactly the step that inflates AUC in most published work.
It is also the method Chaudhary et al. used, so the numbers are directly
comparable.

## 9. The honest number: AUC 0.7235

| Reference standard | AUC |
|---|---|
| METEOR/Fathom model (Part 1) | **0.9545** |
| **Observed flood inventory (126 usable points)** | **0.7235** |
| Chaudhary et al. 2024, same valley, 10 criteria | 0.83 |

**The model looks far better against another model than against reality.**
That gap — 0.95 vs 0.72 — is the single strongest argument for why
model-to-model benchmarking must never be reported as validation.

We also sit below the published 0.83 for the same valley. They used ten
criteria including rainfall, geology and soil; we used six terrain criteria
with uncalibrated thresholds. That is a reasonable explanation, not an
excuse — and it is a concrete target to beat.

**Operationally:** flagging the top 32% of the valley by risk captures 80% of
observed floods. Capturing all of them needs 90% of the area.

## 10. Reality contradicts the METEOR ablation

Per-criterion, against observed floods:

| Criteria | METEOR AUC | **Inventory AUC** |
|---|---|---|
| 6-criterion ensemble | 0.9545 | **0.7235** |
| 3-criterion "pruned" | **0.9627** | **0.7132** (worse) |
| `hand` alone | 0.9041 | **0.6922** |
| `dem_elevation` alone | 0.9060 | 0.6791 |
| `twi` alone | 0.7507 | 0.3936 |
| **`dist_to_river` alone** | 0.8877 | **0.2420** |

`dist_to_river` scores **0.24 — dramatically worse than random (0.5)**. We
checked this directly rather than trusting it:

| | At the 127 flood points | Across the whole valley |
|---|---|---|
| Distance to river | median **620 m** | median **583 m** |
| HAND | median **2.5 m** | median **23.6 m** |

**Not a bug.** Observed flood locations are, if anything, slightly *farther*
from rivers than the valley average — so distance-to-river carries almost no
signal here, and our aggressive reclassification (0–100 m → class 5,
>400 m → class 1) turns that non-signal into an actively wrong one.

**HAND, by contrast, separates flood sites from the valley by roughly 10×
(2.5 m vs 23.6 m).** It is the genuinely strong predictor, and neither
Nepali paper we reviewed uses it.

### Why the two references disagree

METEOR's default layer models **fluvial** (river) flooding. Distance-to-river
predicts it almost tautologically. But real reported flooding in Kathmandu
Valley is substantially **pluvial / urban drainage failure**, which happens
away from river channels.

This is corroborated by Part 1 §6: our model scored 0.95 on METEOR's fluvial
layer but only 0.90 on its pluvial layer. Two independent lines of evidence,
same conclusion.

**Therefore: do not prune criteria based on the METEOR benchmark alone.** The
3-criterion model that *beat* the 6-criterion one against METEOR *loses* to it
against reality.

## 11. Revised recommendations

1. **Report 0.72, not 0.95.** The inventory number is the defensible one.
   Report the METEOR figure separately and label it as model benchmarking.
2. **Recalibrate `dist_to_river` thresholds** against the observed
   distribution (floods at median 620 m), or drop the criterion. Its current
   breaks are demonstrably wrong for this valley — the same
   "borrowed thresholds don't transfer" failure documented in
   `LITERATURE_REVIEW_THRESHOLDS.md`, now confirmed from a second direction.
3. **Lead with HAND.** Strongest real predictor, and an edge over both
   published Nepali studies.
4. **Add rainfall, geology, soil** — the three criteria Chaudhary et al. have
   and we don't, which plausibly explain the 0.72 vs 0.83 gap.
5. **Target pluvial flooding explicitly.** It is what actually gets reported
   in this valley and what our terrain-proxy model handles worst.
6. **Run the prediction-rate curve** (`--split-year 2020`) for a true
   temporal holdout — fit on pre-2020 events, evaluate on post-2020. Stronger
   than the success-rate curve reported here.

## 12. Limitations of the inventory itself

Stated rather than hidden:

* **Reporting bias.** Incidents are recorded where people are. Dense urban
  wards generate more records than empty hillsides regardless of true hazard.
  This is the most likely partial explanation for the `dist_to_river` result
  and must be acknowledged in any write-up.
* **Points, not extents.** Each record is one coordinate, often a ward or
  settlement centroid, not an inundation footprint.
* **Recency bias.** Coverage is much denser after ~2011.
* **Success rate, not prediction rate.** Same inventory used throughout;
  see recommendation 6.

## Reproduce

```bash
docker cp backend/scripts/validate_against_inventory.py \
  floodhubnepal-main-backend-1:/app/validate_against_inventory.py
docker compose exec -T backend python /app/validate_against_inventory.py
docker compose exec -T backend python /app/validate_against_inventory.py --split-year 2020
```

Inventory at `backend/data/raw/flood_inventory/ktm_flood_inventory.json`
(gitignored; regenerate from the BIPAD API).
