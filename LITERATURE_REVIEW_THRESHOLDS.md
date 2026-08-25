# Literature Review — Reclassification Thresholds & AHP Weights

**Purpose:** replace this project's admitted placeholder thresholds with
published, defensible values for the Kathmandu Valley.
**Date:** 2026-08-25
**Status:** partial — one paper extracted in full, two blocked (see §5)

---

## 1. The headline finding: published basin-wide breaks DO NOT transfer

This is the single most important result of the review, and it is empirical,
not an opinion.

The best-matched published study (Bagmati River basin, §2) derives its class
breaks with Jenks natural breaks **over the whole Bagmati basin**, which spans
**53–2,921 m** elevation — from the Terai plains to the Mahabharat range.

Kathmandu Valley is a small, high, comparatively flat sub-basin of that. Our
measured distributions over the pilot AOI (85.22–85.52 E, 27.60–27.82 N):

| | min | p25 | median | p75 | max |
|---|---|---|---|---|---|
| Elevation (m) | 991 | 1,335 | 1,427 | 1,716 | 2,730 |
| Slope (°) | 0.0 | 5.1 | 14.6 | 25.2 | 64.4 |
| Distance to river (m) | 0 | 260 | 583 | 1,087 | 5,179 |

**Applying the published Bagmati breaks to the valley:**

| Published class | Result in Kathmandu Valley |
|---|---|
| Elevation 966–1,491 m = "moderate" | **56.9%** of the valley in one class |
| Elevation < 431 m = "very high" | **0.0%** — class is empty |
| Slope 0–15° = "very high" | **50.8%** of the valley in one class |
| Distance to river 0–150 m = "very high" | 14.9% (this one transfers acceptably) |

Elevation collapses to a single class for more than half the valley, and its
top-risk class is **completely unpopulated**. Slope does much the same. A
model built on these breaks would tell a citizen that essentially the whole
valley is identically risky — which is worse than useless for the stated use
case of *comparing two plots of land*.

**Conclusion:** borrowing absolute thresholds from a study whose study area
differs in scale and relief is not more rigorous than estimating them; it is
*differently* wrong, and harder to notice. Rigour here means deriving breaks
from the actual distribution of the actual AOI, and validating the result.

**Recommendation:** use **AOI-derived Jenks or quantile breaks** — which the
backend already supports (`POST /api/overlay/criteria/breaks`) — and cite the
literature for the *method* and the *risk direction*, not for the numbers.
That is exactly what the Bagmati paper itself did: it computed Jenks breaks
on its own study area rather than importing someone else's.

## 2. Source: Bagmati River basin (best available match)

> Flood vulnerability map of the Bagmati River basin, Nepal: a comparative
> approach of the analytical hierarchy process and frequency ratio model.
> *Smart Construction and Sustainable Cities* (2024).
> https://doi.org/10.1007/s44268-024-00041-7

Directly relevant: Kathmandu Valley is the upstream section of this basin.
The paper explicitly notes the valley "appeared more vulnerable to flooding"
in its frequency-ratio model.

### 2.1 AHP weights (extracted)

| Factor | Weight |
|---|---|
| **Precipitation** | **0.14** (highest) |
| NDVI | 0.058 |
| Soil classification | 0.057 (lowest) |

Only the extremes are stated in the text; the full weight table is in a
figure/table we could not extract. **Precipitation carrying the highest
weight independently corroborates the Parajuli (Siraha) finding** that
rainfall is a top-2 factor — and this project still has no rainfall criterion
merged.

Method: Saaty pairwise comparison, eigenvector, CI/CR validated. Validated
with AUC against a flood inventory.

### 2.2 Class breaks (Jenks, whole basin — see §1 before using)

**Elevation** (basin range 53–2,921 m)
| Range | Susceptibility |
|---|---|
| 53–431 m | very high |
| 431–966 m | high |
| 966–1,491 m | moderate |
| 1,491–1,920 m | low |
| 1,920–2,921 m | very low |

**Slope** (manual, not Jenks)
| Range | Susceptibility |
|---|---|
| 0–15° | very high |
| 15–30° | high |
| 30–45° | moderate |
| 45–60° | low |
| 60–71.3° | very low |

**Distance from river** (Euclidean, Jenks) — *the one that transfers best*
| Range | Susceptibility |
|---|---|
| 0–150 m | very high |
| 150–513 m | high |
| 513–1,150 m | moderate |
| 1,150–1,630 m | low |
| 1,630–2,864 m | very low |

**Drainage density** (km/km², Jenks)
| Range | Susceptibility |
|---|---|
| 0.035–0.337 | very low |
| 0.337–0.521 | low |
| 0.521–0.685 | moderate |
| 0.685–0.863 | high |
| 0.863–1.305 | very high |

**NDVI** (Jenks)
| Range | Class label in paper |
|---|---|
| −0.266–0.116 | very low |
| 0.116–0.183 | low |
| 0.183–0.245 | moderate |
| 0.245–0.309 | high |
| 0.309–0.530 | very high |

⚠️ The paper's NDVI labels appear to describe the *NDVI value*, not the flood
risk — higher NDVI (denser vegetation) normally means *lower* flood risk.
Do not copy this direction without checking the figure. Our own
`criteria.js` uses the conventional inverse direction.

**Soil type** (manual, FAO units)
low: loam Bd35-1/2b · moderate: loam Je77-1/2a · high: loam Bd34-2bc ·
very high: clay Rd30-2b

**Flow accumulation** (Jenks): 0–119,377 (very low) → 2,356,501–3,664,590
(very high)

### 2.3 Methodological note worth copying

The paper classifies **elevation, distance-from-river, drainage density,
flow accumulation, TWI and NDVI with Jenks natural breaks on its own study
area**, and only **soil, slope and LULC manually** by physical
characteristics. That split is a sound convention and matches our §1
recommendation: continuous terrain variables get data-derived breaks;
categorical/physical ones get expert breaks.

## 3. Secondary source: Lamjung District, Nepal

> Flood susceptibility mapping in a Himalayan mountain basin using GIS and
> multi-criteria analysis. *Arabian Journal of Geosciences* (2026).
> https://doi.org/10.1007/s12517-026-12558-5

Nine factors at 10 m resolution — the same resolution this project uses.

| Factor | Weight |
|---|---|
| Distance to river | 0.156 |
| TWI | 0.152 |
| Rainfall | 0.151 |

**Consistency Ratio = 0.037** (well under the 0.10 threshold).

Note the tension with our own METEOR benchmarking, which found TWI has
*negative* marginal value in Kathmandu Valley. A Himalayan mountain basin and
an urban valley floor are different hydrological settings; this is a reason to
prefer locally-validated weights over borrowed ones.

## 4. Cross-check against our METEOR benchmarking

| Factor | Published emphasis | Our measured solo AUC | Our ablation Δ |
|---|---|---|---|
| Distance to river | highest/near-highest in both papers | 0.8877 | **−0.0206** (most valuable) |
| Elevation | high | **0.9060** (best) | −0.0126 |
| HAND | not used in either paper | **0.9041** | −0.0164 |
| Slope | moderate | 0.8422 | +0.0019 (no value) |
| TWI | 0.152 (Lamjung, high) | 0.7507 | **+0.0033 (harmful)** |
| Drainage density | moderate | 0.7132 | **+0.0026 (harmful)** |
| Precipitation | **0.14, highest** (Bagmati) | not yet merged | — |

**Agreement:** distance-to-river is genuinely important — literature and our
own measurement both say so.

**Disagreement:** TWI is weighted highly in the literature but measurably
harmful in our valley benchmark. Our own evidence should win for our own
study area, and the disagreement is worth reporting rather than hiding.

**Gap:** every paper reviewed puts precipitation at or near the top. We have
no rainfall criterion merged. This is now corroborated by three independent
sources (Parajuli/Siraha, Bagmati, Lamjung).

**HAND is our edge:** neither paper uses it, and it is our second-best
single predictor. Worth writing up.

## 5. Blocked sources — need manual download

MDPI is behind Cloudflare and refuses automated fetching (HTTP 403 via
publisher, DOI, Unpaywall and CGSpace routes). These are **open access** and
download normally in a browser:

1. **Flood Susceptibility and Risk Mapping of Kathmandu Valley Watershed,
   Nepal** — *Sustainability* 16(16), 7101 (2024).
   https://doi.org/10.3390/su16167101
   **The single most relevant paper in existence for this project.** Ten
   parameters, AHP eigenvector weights, exact study area. Known from the
   abstract: ~80% of the valley is moderate-to-low susceptibility, ~14% highly
   susceptible along riverbanks — a useful sanity check for our own output
   distribution.

2. **Impact of Urbanization on Flooding and Risk … Kathmandu Valley** —
   *Hydrology* 12(11), 283 (2025). https://doi.org/10.3390/hydrology12110283
   Hydrologic–hydraulic modelling plus AHP for the same area.

**Action:** download both PDFs to `E:\Project2\evacuation\` and I will extract
the tables the same way I did for the Bagmati paper.

## 6. Recommendations

1. **Do not hard-code borrowed absolute breaks.** §1 shows they destroy
   discrimination inside the valley. Cite literature for method and risk
   direction; derive numbers from the AOI.
2. **Default the citizen profile to Jenks breaks** computed on the valley
   surface, using the existing `/api/overlay/criteria/breaks` endpoint.
3. **Adopt the Bagmati split:** data-derived breaks for continuous terrain
   variables, manual/physical breaks for categorical ones (soil, LULC).
4. **Distance-to-river breaks are the exception** — the published values
   (150/513/1,150/1,630 m) sit sensibly within our observed range and are
   worth adopting directly with citation.
5. **Get rainfall merged.** Three independent papers rank precipitation top.
6. **Report the TWI disagreement openly.** Literature says high weight, our
   benchmark says harmful here. That contrast is a finding, not an
   embarrassment.
7. **Sanity-check against the Kathmandu Valley paper** once obtained: if our
   surface says ~14% highly susceptible concentrated on riverbanks, that is
   independent corroboration.
