"""Exception types raised by the AHP engine."""

from __future__ import annotations

from typing import Any


class AHPValidationError(ValueError):
    """A pairwise comparison matrix is structurally invalid.

    Raised for shape mismatches, non-positive entries, a diagonal that
    isn't 1, or an (i, j)/(j, i) pair that isn't reciprocal — i.e. the
    input isn't a valid Saaty pairwise comparison matrix at all, before
    any priority-weight computation is attempted.
    """


class AHPConsistencyError(ValueError):
    """One or more pairwise comparison matrices failed the CR < 0.10 check.

    Carries enough detail about each failing matrix (its CR, and its
    least-consistent judgments) to tell the caller exactly what to
    reconsider, per Saaty, T.L. (2003). "Decision-making with the AHP:
    Why is the principal eigenvector necessary?" European Journal of
    Operational Research, 145(1), 85-91 — which identifies the
    least-consistent judgment in a matrix as the (i, j) pair whose
    epsilon_ij = a_ij * w_j / w_i deviates furthest from 1.
    """

    def __init__(self, failures: list[dict[str, Any]]):
        self.failures = failures
        summary = "; ".join(
            f"{f['matrix']}: CR={f['consistency_ratio']:.4f} (threshold 0.10)"
            for f in failures
        )
        super().__init__(f"Inconsistent pairwise comparison matrix/matrices: {summary}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "ahp_consistency_check_failed",
            "message": str(self),
            "failures": self.failures,
        }
