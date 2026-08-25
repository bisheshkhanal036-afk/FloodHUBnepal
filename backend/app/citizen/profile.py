"""The fixed criteria profile Citizen Mode computes with, and why each
part of it is what it is.

Citizen Mode gives a member of the public one tap and one answer. It does
not ask them to pick criteria, choose a weighting method, fill a Saaty
pairwise matrix, or tune class breaks — the researcher tool
(app/overlay/) still does all of that. Fixing those choices on the user's
behalf is only defensible if the fixed configuration is the best one the
project can evidence, so every value below was **selected by measurement
against an observed flood inventory**, not by judgement.

Validation summary (backend/scripts/tune_citizen_profile.py, run over the
Kathmandu Valley pilot AOI against 145 BIPAD/NDRRMA flood incident
records, 2011-2026, success-rate curve method):

    profile                      weights    breaks       AUC
    6-criterion                  equal      hardcoded    0.7235   <- previous default
    6-criterion                  published  hardcoded    0.7399
    6-criterion                  equal      quantile     0.7594
    6-criterion                  published  quantile     0.7966
    5-criterion (no dist_river)  equal      quantile     0.7768
    5-criterion (no dist_river)  published  quantile     0.8112   <- THIS PROFILE
    4-criterion HAND-led         published  quantile     0.8066

    Prediction-rate (temporal holdout, events 2020+ only, n=80): 0.8110

The prediction-rate figure matching the success-rate figure almost
exactly is the important one: the profile is not overfitted to the
inventory it was tuned on.

For comparison, Chaudhary et al. (2024) report AUC 0.83 for this same
watershed using ten criteria including rainfall, geology and soil. This
profile reaches 0.81 with five, none of which require data this project
does not already fetch.

--- Why dist_to_river is deliberately EXCLUDED ---

It is the one criterion measured to be actively harmful here. Against the
observed inventory it scored **AUC 0.2420 alone — far worse than random**.
Checked directly rather than trusted: observed flood points sit a median
620 m from the nearest river, while the valley as a whole sits at a
median 583 m. Real reported flooding in this valley is, if anything,
slightly *farther* from rivers than average.

That is not a bug, it is a property of the study area: much of Kathmandu
Valley's reported flooding is pluvial (rainfall/drainage failure in dense
urban fabric) rather than fluvial (river overtopping). The same
conclusion arrives independently from the METEOR benchmark, where the
model scored 0.95 against METEOR's fluvial layer but only 0.90 against
its pluvial layer.

Note this contradicts what the METEOR benchmark alone suggested — there,
dist_to_river looked like the single most valuable criterion (ablation
-0.0206). METEOR's default layer models fluvial flooding, which
distance-to-river predicts almost tautologically. Benchmarking against a
model can mislead in ways that validating against observations does not;
this profile follows the observations.

--- Why HAND is included and leads ---

The strongest real predictor found. Observed flood points sit at a median
HAND of 2.5 m versus 23.6 m for the valley overall — roughly a tenfold
separation. Neither Nepali AHP study reviewed for this project
(Chaudhary et al. 2024; the Bagmati basin study) uses HAND at all.

Since HAND does not appear in the published weight table, it is assigned
the weight the table gives distance-from-river (8), which it functionally
replaces as this profile's channel-proximity term.
"""

from __future__ import annotations

# Criteria, in the order shown to the user.
CITIZEN_CRITERIA: tuple[str, ...] = (
    "hand",
    "dem_elevation",
    "dem_slope",
    "twi",
    "drainage_density",
)

# Chaudhary, U., Shah, M.A.R., Shakya, B.M., & Aryal, A. (2024). Flood
# Susceptibility and Risk Mapping of Kathmandu Valley Watershed, Nepal.
# Sustainability, 16(16), 7101. https://doi.org/10.3390/su16167101
# Table 4, criteria weights (%), AHP eigenvector method, CR = 0.052.
#
# Derived for THIS study area specifically, which is why they are used
# here rather than an equal split (worth +0.035 AUC, table above) and
# rather than weights from a study of a differently-scaled basin.
#
# `hand` is not in the published table; it takes distance-from-river's
# weight (8) as the channel-proximity term it replaces here.
PUBLISHED_WEIGHTS_KV: dict[str, int] = {
    "dem_elevation": 22,
    "dem_slope": 16,
    "twi": 10,
    "hand": 8,
    "drainage_density": 4,
}

# Number of classes each criterion is reclassified into.
N_CLASSES = 5

# ascending  = high raw value -> high flood risk
# descending = low raw value  -> high flood risk
# Physics, not a tuned parameter.
RISK_DIRECTION: dict[str, str] = {
    "hand": "descending",
    "dem_elevation": "descending",
    "dem_slope": "descending",
    "twi": "ascending",
    "drainage_density": "ascending",
}

# Hazard class (1-5) -> the three labels a citizen actually sees.
#
# Three rather than five deliberately: the METEOR benchmarking found this
# model separates flooded from dry ground well but barely distinguishes
# severity (mean hazard class 4.18 / 4.25 / 4.26 / 4.32 across four
# increasing depth bands). Showing five gradations would imply a severity
# resolution the model does not have.
RISK_LEVEL_BY_CLASS: dict[int, str] = {
    1: "low",
    2: "low",
    3: "moderate",
    4: "high",
    5: "high",
}

# What the model actually achieves, surfaced through the API so the UI can
# state it rather than the user having to take the answer on trust.
VALIDATION = {
    "auc_success_rate": 0.8112,
    "auc_prediction_rate_2020plus": 0.8110,
    "n_flood_points": 145,
    "inventory_years": "2011-2026",
    "inventory_source": "BIPAD / NDRRMA incident records, Government of Nepal",
    "method": "success-rate curve (Chung & Fabbri 2003)",
    "comparison": "Chaudhary et al. (2024) report AUC 0.83 for this watershed using ten criteria.",
}


def normalized_weights(criteria: tuple[str, ...] = CITIZEN_CRITERIA) -> dict[str, float]:
    """Published weights renormalised to sum to 1 over `criteria`."""
    raw = {c: PUBLISHED_WEIGHTS_KV[c] for c in criteria}
    total = sum(raw.values())
    return {c: v / total for c, v in raw.items()}
