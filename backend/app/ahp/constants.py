"""Constants for the AHP engine: Saaty's Random Index table, the AHP
hierarchy's canonical cluster names, and the consistency threshold.

Citation
--------
Saaty, T.L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill, New York.
Original source of both the eigenvector priority method and the Random
Index (RI) table used to compute the Consistency Ratio (CR = CI / RI).
"""

from __future__ import annotations

# Saaty's Random Index (RI): the average Consistency Index of a large
# number of randomly generated n x n reciprocal matrices with entries
# drawn from the Saaty 1-9 scale. Used as the denominator of CR = CI / RI.
#
# Values for n = 1..10 are reproduced here exactly as they appear in
# Parajuli et al. (2023, Table 6 [https://doi.org/10.3390/ijgi12070286]),
# which in turn cites Saaty (1980) directly, and were independently
# cross-checked against that paper's PDF during implementation of this
# module.
#
# Values for n = 11..15 extend beyond what either primary source we
# verified against actually tabulates (both stop at n = 10). Saaty's own
# published extensions to n = 15 vary slightly across editions and
# secondary sources reproducing them (e.g. n=11 is given as 1.51 in some
# sources and 1.52 in others). The values below follow the commonly
# reproduced extension (Saaty, 1980/2000); if a request ever needs an
# exact match to a specific edition's table for n > 10, that value should
# be re-verified against the specific edition in question rather than
# assumed from this table.
RANDOM_INDEX: dict[int, float] = {
    1: 0.00,
    2: 0.00,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
    11: 1.51,
    12: 1.48,
    13: 1.56,
    14: 1.57,
    15: 1.59,
}

# Per SPEC.md, "AHP Pairwise Matrix": CR < 0.10 is the pass threshold.
CONSISTENCY_RATIO_THRESHOLD = 0.10

# The 5 top-level AHP clusters, fixed by schemas/criterion.schema.json and
# schemas/ahp_pairwise_matrix.schema.json. The top-level cluster_comparison
# matrix must compare exactly these 5 items; within_cluster_comparisons
# keys must each be one of these 5 names.
CANONICAL_CLUSTERS: tuple[str, ...] = (
    "Topographic",
    "Hydrological",
    "Land Use",
    "Infrastructure",
    "Exposure",
)

# Floating-point tolerance used when validating that a matrix's diagonal
# is 1 and that it is reciprocal (a[j][i] == 1 / a[i][j]).
VALIDATION_TOLERANCE = 1e-6
