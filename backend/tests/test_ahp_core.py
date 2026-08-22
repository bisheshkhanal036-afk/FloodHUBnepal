"""Unit tests for app/ahp/core.py against known matrices.

Every non-synthetic matrix here is transcribed from a real published
source and cross-checked (column sums / reciprocity / weight sums) against
that source during test authoring — see the citation in each test's
docstring. This is deliberate: the eigenvector math is the core of the
whole tool's validity, so these tests check the numbers are exactly
right, not merely "in the right ballpark".
"""

from __future__ import annotations

import numpy as np
import pytest

from app.ahp.core import compute_priority_vector
from app.ahp.errors import AHPValidationError


def test_perfectly_consistent_matrix_recovers_exact_weights():
    """A matrix built as a[i][j] = w[i] / w[j] from known weights is
    perfectly consistent by construction: Saaty (1980) proves such a
    matrix has lambda_max exactly n, CI = 0, CR = 0, and its principal
    eigenvector is exactly w (normalized). This is a synthetic matrix
    (not itself a published example) used to exercise that mathematical
    identity directly, as a sanity check independent of any literature
    source.
    """
    true_weights = np.array([4.0, 2.0, 1.0, 0.5])
    true_weights /= true_weights.sum()
    n = len(true_weights)
    matrix = [[true_weights[i] / true_weights[j] for j in range(n)] for i in range(n)]
    items = ["A", "B", "C", "D"]

    result = compute_priority_vector(matrix, items)

    assert result.lambda_max == pytest.approx(n, abs=1e-9)
    assert result.consistency_index == pytest.approx(0.0, abs=1e-9)
    assert result.consistency_ratio == pytest.approx(0.0, abs=1e-9)
    assert result.consistent is True
    assert result.eigenvector_weights == pytest.approx(list(true_weights), abs=1e-9)
    # For a perfectly consistent matrix the approximation method is also
    # exact (Jensen, 1984, notes the two methods only diverge as
    # inconsistency grows) — both methods should agree here.
    assert result.approximate_weights == pytest.approx(list(true_weights), abs=1e-9)


@pytest.mark.parametrize("n", [1, 2])
def test_matrices_below_size_3_are_trivially_consistent(n):
    """RI is 0 for n <= 2 (Saaty, 1980's Random Index table), so CR is
    defined as 0.0 by convention. For n=2 this is also true
    mathematically for *any* positive reciprocal 2x2 matrix: its
    characteristic polynomial is lambda^2 - 2*lambda + (1 - a*(1/a)) =
    lambda^2 - 2*lambda = 0, giving eigenvalues {0, 2} regardless of the
    judgment value a, so lambda_max is always exactly 2 = n.
    """
    if n == 1:
        matrix, items = [[1.0]], ["A"]
    else:
        matrix, items = [[1.0, 7.0], [1 / 7, 1.0]], ["A", "B"]

    result = compute_priority_vector(matrix, items)

    assert result.lambda_max == pytest.approx(n, abs=1e-9)
    assert result.consistency_ratio == pytest.approx(0.0, abs=1e-9)
    assert result.consistent is True


def test_saaty_2003_house_buying_matrix_eigenvector_method():
    """Saaty, T.L. (2003). "Decision-making with the AHP: Why is the
    principal eigenvector necessary?" European Journal of Operational
    Research, 145(1), 85-91, Table 1: "A family's house buying pairwise
    comparison matrix for the criteria" (8 criteria: Size, Transportation,
    Neighborhood, Age, Yard, Modern facilities, Condition, Financing).

    The paper publishes the exact eigenvector-method weights (its "w"
    column), lambda_max = 9.669, and CR = 0.17 for this matrix — verified
    directly against the paper's PDF (Table 1, p. 88). This is also a
    genuine literature example of a matrix that *fails* the CR < 0.10
    check (Saaty uses it specifically to demonstrate how to diagnose and
    fix an inconsistent matrix), so it doubles as the test that our
    consistency rejection triggers correctly on real, published data.
    """
    items = ["Size", "Trans", "Nbrhd", "Age", "Yard", "Modern", "Cond", "Finance"]
    matrix = [
        [1, 5, 3, 7, 6, 6, 1 / 3, 1 / 4],
        [1 / 5, 1, 1 / 3, 5, 3, 3, 1 / 5, 1 / 7],
        [1 / 3, 3, 1, 6, 3, 4, 6, 1 / 5],
        [1 / 7, 1 / 5, 1 / 6, 1, 1 / 3, 1 / 4, 1 / 7, 1 / 8],
        [1 / 6, 1 / 3, 1 / 3, 3, 1, 1 / 2, 1 / 5, 1 / 6],
        [1 / 6, 1 / 3, 1 / 4, 4, 2, 1, 1 / 5, 1 / 6],
        [3, 5, 1 / 6, 7, 5, 5, 1, 1 / 2],
        [4, 7, 5, 8, 6, 6, 2, 1],
    ]
    published_weights = [0.173, 0.054, 0.188, 0.018, 0.031, 0.036, 0.167, 0.333]

    result = compute_priority_vector(matrix, items)

    assert result.lambda_max == pytest.approx(9.669, abs=0.01)
    assert result.consistency_ratio == pytest.approx(0.17, abs=0.01)
    assert result.eigenvector_weights == pytest.approx(published_weights, abs=0.005)
    # The paper's own point: this matrix should be flagged as inconsistent.
    assert result.consistent is False
    assert result.consistency_ratio >= 0.10
    assert len(result.worst_pairs) > 0


def test_parajuli_2023_flood_matrix_approximate_method():
    """Parajuli, G., Neupane, S., Kunwar, S., Adhikari, R., Acharya, T.D.
    (2023). "A GIS-Based Evacuation Route Planning in Flood-Susceptible
    Area of Siraha Municipality, Nepal." ISPRS International Journal of
    Geo-Information, 12(7), 286. Table 4 (pairwise comparison matrix) and
    Table 5 (normalized matrix and criteria weights) for the 9 flood
    conditioning factors: Elevation (EL), Slope (SL), Precipitation (PP),
    Distance from River (DRI), Drainage Density (DD), Topographic Wetness
    Index (TWI), Land Use/Land Cover (LULC), NDVI, Distance from Road
    (DRO).

    IMPORTANT: this paper explicitly computed weights via the
    approximation method (normalize columns by their sum, then average
    each row) — it is not an eigenvector-method example. So this test
    compares against `approximate_weights`, not `eigenvector_weights`.
    Matrix and published weights were transcribed from the paper's PDF
    (Tables 4-5, pp. 9) and independently cross-checked cell-by-cell
    against the paper's own reported column sums (Table 4's "Sum" row)
    and row weight sums (Table 5) before being hardcoded here.
    """
    items = ["EL", "SL", "PP", "DRI", "DD", "TWI", "LULC", "NDVI", "DRO"]
    matrix = [
        [1, 2, 1 / 3, 1 / 3, 1, 1, 2, 2, 3],
        [1 / 2, 1, 1 / 2, 1 / 3, 2 / 3, 2, 1, 2, 1],
        [3, 2, 1, 1 / 2, 1, 3, 3, 3, 5],
        [3, 3, 2, 1, 1, 3, 3, 3, 5],
        [1, 1.5, 1, 1, 1, 3, 2, 4, 1],
        [1, 1 / 2, 1 / 3, 1 / 3, 1 / 3, 1, 1, 1, 8],
        [1 / 2, 1, 1 / 3, 1 / 3, 1 / 2, 1, 1, 1, 3],
        [1 / 2, 1 / 2, 1 / 3, 1 / 3, 1 / 4, 1, 1, 1, 3],
        [1 / 3, 1, 1 / 5, 1 / 5, 1, 1 / 8, 1 / 3, 1 / 3, 1],
    ]
    published_approximate_weights = [0.106, 0.082, 0.179, 0.219, 0.151, 0.086, 0.069, 0.061, 0.047]

    # Sanity-check the transcription itself against the paper's own
    # published column sums (Table 4) before trusting the weight
    # comparison below.
    published_column_sums = [10.83, 12.50, 6.03, 4.37, 6.75, 15.13, 14.33, 17.33, 30.00]
    column_sums = np.array(matrix).sum(axis=0)
    assert column_sums == pytest.approx(published_column_sums, abs=0.01)

    result = compute_priority_vector(matrix, items)

    assert result.approximate_weights == pytest.approx(published_approximate_weights, abs=0.002)
    assert sum(result.approximate_weights) == pytest.approx(1.0, abs=1e-9)


def test_rejects_non_reciprocal_matrix():
    items = ["A", "B", "C"]
    # matrix[0][1] = 3 but matrix[1][0] = 0.5, not the required 1/3.
    matrix = [[1, 3, 5], [0.5, 1, 4], [1 / 5, 1 / 4, 1]]

    with pytest.raises(AHPValidationError):
        compute_priority_vector(matrix, items)


def test_rejects_non_positive_entry():
    items = ["A", "B"]
    matrix = [[1, -2], [-0.5, 1]]

    with pytest.raises(AHPValidationError):
        compute_priority_vector(matrix, items)


def test_rejects_diagonal_not_one():
    items = ["A", "B"]
    matrix = [[1.5, 2], [0.5, 1]]

    with pytest.raises(AHPValidationError):
        compute_priority_vector(matrix, items)


def test_rejects_shape_mismatch():
    items = ["A", "B", "C"]
    matrix = [[1, 2], [0.5, 1]]

    with pytest.raises(AHPValidationError):
        compute_priority_vector(matrix, items)


def test_worst_pairs_flags_the_known_culprit_in_saaty_house_matrix():
    """Saaty (2003) identifies the (Neighborhood, Condition) judgment
    (a_37 = 6, table position "Nbrhd" row / "Cond" column) as the single
    largest contributor to this matrix's inconsistency (epsilon = 5.32156,
    Table 3, p. 89 — the largest value in that table). Our worst-pairs
    diagnostic, built on the same epsilon_ij = a_ij * w_j / w_i method,
    should surface that same pair first.
    """
    items = ["Size", "Trans", "Nbrhd", "Age", "Yard", "Modern", "Cond", "Finance"]
    matrix = [
        [1, 5, 3, 7, 6, 6, 1 / 3, 1 / 4],
        [1 / 5, 1, 1 / 3, 5, 3, 3, 1 / 5, 1 / 7],
        [1 / 3, 3, 1, 6, 3, 4, 6, 1 / 5],
        [1 / 7, 1 / 5, 1 / 6, 1, 1 / 3, 1 / 4, 1 / 7, 1 / 8],
        [1 / 6, 1 / 3, 1 / 3, 3, 1, 1 / 2, 1 / 5, 1 / 6],
        [1 / 6, 1 / 3, 1 / 4, 4, 2, 1, 1 / 5, 1 / 6],
        [3, 5, 1 / 6, 7, 5, 5, 1, 1 / 2],
        [4, 7, 5, 8, 6, 6, 2, 1],
    ]

    result = compute_priority_vector(matrix, items)

    top = result.worst_pairs[0]
    assert {top.item_i, top.item_j} == {"Nbrhd", "Cond"}
