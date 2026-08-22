"""Core AHP math: priority-weight computation and consistency checking for
a single n x n pairwise comparison matrix.

Two ways of turning a Saaty pairwise comparison matrix into priority
weights are implemented and both are always returned:

- ``eigenvector_weights`` (**primary**): the exact eigenvector method —
  the principal (Perron) eigenvector of the matrix, normalized to sum to
  1. This is the method used for every downstream weight in this system
  (Criterion.weight, RiskSurface composition, etc).
- ``approximate_weights`` (**diagnostic only**): the classic approximation
  — normalize each column by its column sum, then average each row.
  Returned purely for comparison; nothing downstream consumes it.

Citations
---------
Saaty, T.L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill, New
York. Original source of the eigenvector method, the CI/CR consistency
formulas, and the Random Index table (see constants.py).

Jensen, R.E. (1984). "An alternative scaling method for priorities in
hierarchical structures." Journal of Mathematical Psychology, 28(3),
317-332. Simulation evidence that the exact eigenvector method recovers
the true underlying ratio-scale weights more reliably than the column-
normalize-and-average approximation, especially as matrix inconsistency
grows — the reason the eigenvector method is primary here and the
approximation is diagnostic-only, not the reverse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .constants import CONSISTENCY_RATIO_THRESHOLD, RANDOM_INDEX, VALIDATION_TOLERANCE
from .errors import AHPValidationError


@dataclass(frozen=True)
class WorstPair:
    """One judgment flagged as a contributor to a matrix's inconsistency.

    ``epsilon`` is a_ij * w_j / w_i (Saaty, 2003) — 1.0 for a judgment
    that is perfectly consistent with the rest of the matrix; the further
    from 1.0, the more that single judgment is pulling lambda_max above n.
    """

    item_i: str
    item_j: str
    judgment: float
    epsilon: float


@dataclass(frozen=True)
class PairwiseResult:
    """Full result of computing priority weights for one pairwise matrix."""

    items: list[str]
    matrix: list[list[float]]
    eigenvector_weights: list[float]
    approximate_weights: list[float]
    lambda_max: float
    consistency_index: float
    random_index: float
    consistency_ratio: float
    consistent: bool
    worst_pairs: list[WorstPair] = field(default_factory=list)


def validate_matrix(matrix: np.ndarray, items: list[str]) -> None:
    """Raise AHPValidationError if `matrix` is not a valid Saaty pairwise
    comparison matrix for `items`: square, matching `items`' length,
    positive, diagonal of 1s, and reciprocal (a[j][i] == 1 / a[i][j]).
    """
    n = len(items)
    if len(set(items)) != n:
        raise AHPValidationError(f"items must be unique; got {items!r}")
    if matrix.shape != (n, n):
        raise AHPValidationError(
            f"matrix shape {matrix.shape} does not match {n} items {items!r}"
        )
    if np.any(matrix <= 0):
        i, j = np.argwhere(matrix <= 0)[0]
        raise AHPValidationError(
            f"matrix[{items[i]}][{items[j]}] = {matrix[i, j]} is not positive; "
            "all pairwise comparison values must be > 0"
        )
    for i in range(n):
        if not math.isclose(matrix[i, i], 1.0, rel_tol=VALIDATION_TOLERANCE):
            raise AHPValidationError(
                f"matrix[{items[i]}][{items[i]}] = {matrix[i, i]}, diagonal entries must be 1"
            )
    for i in range(n):
        for j in range(i + 1, n):
            product = matrix[i, j] * matrix[j, i]
            if not math.isclose(product, 1.0, rel_tol=1e-4):
                raise AHPValidationError(
                    f"matrix[{items[i]}][{items[j]}]={matrix[i, j]} and "
                    f"matrix[{items[j]}][{items[i]}]={matrix[j, i]} are not reciprocal "
                    f"(product = {product}, expected 1)"
                )


def eigenvector_priority_weights(matrix: np.ndarray) -> tuple[np.ndarray, float]:
    """The exact eigenvector method (Saaty, 1980): the principal
    eigenvector of `matrix`, normalized to sum to 1, and its eigenvalue
    (lambda_max).

    Per Saaty's Perron-Frobenius argument, a positive reciprocal matrix
    has a unique largest real eigenvalue (lambda_max >= n, with equality
    iff the matrix is perfectly consistent) whose eigenvector is strictly
    positive; that eigenvector, normalized, is the priority vector.
    """
    n = matrix.shape[0]
    if n == 1:
        return np.array([1.0]), 1.0

    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    idx = int(np.argmax(eigenvalues.real))
    lambda_max = float(eigenvalues[idx].real)
    vector = eigenvectors[:, idx].real

    # The Perron eigenvector is unique up to a scalar multiple and is
    # strictly one-signed; normalize sign then scale, so it sums to 1.
    if vector.sum() < 0:
        vector = -vector
    if np.any(vector < -VALIDATION_TOLERANCE):
        raise AHPValidationError(
            "principal eigenvector is not one-signed; the input matrix is not a "
            "valid positive reciprocal pairwise comparison matrix"
        )
    vector = np.clip(vector, 0, None)
    weights = vector / vector.sum()
    return weights, lambda_max


def approximate_priority_weights(matrix: np.ndarray) -> np.ndarray:
    """The approximation method (diagnostic only — see module docstring):
    normalize each column by its column sum, then average across each row.
    """
    column_sums = matrix.sum(axis=0)
    normalized = matrix / column_sums
    return normalized.mean(axis=1)


def consistency_index(lambda_max: float, n: int) -> float:
    """CI = (lambda_max - n) / (n - 1) (Saaty, 1980)."""
    if n <= 1:
        return 0.0
    return (lambda_max - n) / (n - 1)


def consistency_ratio(ci: float, n: int) -> tuple[float, float]:
    """CR = CI / RI (Saaty, 1980). Returns (cr, ri).

    RI is 0 for n <= 2 (every 2x2 positive reciprocal matrix is
    automatically consistent: its eigenvalues are exactly n and 0), so CR
    is defined as 0.0 by convention rather than dividing by zero.
    """
    if n not in RANDOM_INDEX:
        raise AHPValidationError(
            f"no Random Index defined for a {n}x{n} matrix; the RI table covers n=1..15"
        )
    ri = RANDOM_INDEX[n]
    if ri == 0.0:
        return 0.0, ri
    return ci / ri, ri


def find_worst_pairs(
    matrix: np.ndarray, weights: np.ndarray, items: list[str], top_k: int = 3
) -> list[WorstPair]:
    """Identify the `top_k` least-consistent judgments in `matrix`, per
    Saaty (2003): epsilon_ij = a_ij * w_j / w_i should equal 1 for a
    perfectly consistent judgment; rank by how far ln(epsilon_ij) is from
    0 (equivalently, how far epsilon_ij is from 1 on a ratio scale).
    """
    n = len(items)
    if n < 3:
        return []
    w = weights
    ratio = np.outer(1.0 / w, w)  # ratio[i, j] = w_j / w_i
    epsilon = matrix * ratio

    candidates = []
    for i in range(n):
        for j in range(i + 1, n):
            deviation = abs(math.log(epsilon[i, j]))
            candidates.append((deviation, i, j))
    candidates.sort(key=lambda t: t[0], reverse=True)

    return [
        WorstPair(
            item_i=items[i],
            item_j=items[j],
            judgment=float(matrix[i, j]),
            epsilon=float(epsilon[i, j]),
        )
        for _, i, j in candidates[:top_k]
    ]


def compute_priority_vector(matrix_values: list[list[float]], items: list[str]) -> PairwiseResult:
    """Compute both priority-weight methods and full consistency
    diagnostics for one pairwise comparison matrix. Does not raise on
    CR >= 0.10 — see PairwiseResult.consistent; callers that must reject
    inconsistent matrices (the hierarchy composition, the API) do so
    explicitly using that flag.
    """
    matrix = np.array(matrix_values, dtype=float)
    validate_matrix(matrix, items)

    n = len(items)
    eigenvector_weights, lambda_max = eigenvector_priority_weights(matrix)
    approx_weights = approximate_priority_weights(matrix)
    ci = consistency_index(lambda_max, n)
    cr, ri = consistency_ratio(ci, n)
    consistent = cr < CONSISTENCY_RATIO_THRESHOLD
    worst_pairs = [] if consistent else find_worst_pairs(matrix, eigenvector_weights, items)

    return PairwiseResult(
        items=list(items),
        matrix=[[float(v) for v in row] for row in matrix_values],
        eigenvector_weights=[float(v) for v in eigenvector_weights],
        approximate_weights=[float(v) for v in approx_weights],
        lambda_max=lambda_max,
        consistency_index=ci,
        random_index=ri,
        consistency_ratio=cr,
        consistent=consistent,
        worst_pairs=worst_pairs,
    )
