"""Pydantic request/response models for POST /api/ahp/compute.

The request shape mirrors the input fields of the `pairwiseMatrix` $def in
schemas/ahp_pairwise_matrix.schema.json (items + matrix). The response is
a superset of that schema's output fields: it adds `approximate_weights`,
`consistent`, and `worst_pairs`, which the schema's stored/canonical
`AhpPairwiseMatrix` object doesn't carry — only `eigenvector_weights` maps
back onto that schema's `weights` field when a result is persisted.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .core import PairwiseResult
from .hierarchy import HierarchyResult


class PairwiseMatrixInput(BaseModel):
    items: list[str] = Field(..., min_length=1, description="Ordered ids being compared.")
    matrix: list[list[float]] = Field(..., description="n x n Saaty pairwise comparison matrix.")

    @field_validator("matrix")
    @classmethod
    def _matrix_is_square_list(cls, v: list[list[float]]) -> list[list[float]]:
        if not v or any(len(row) != len(v) for row in v):
            raise ValueError("matrix must be a non-empty square (n x n) list of lists")
        return v


class AHPComputeRequest(BaseModel):
    cluster_comparison: PairwiseMatrixInput
    within_cluster_comparisons: dict[str, PairwiseMatrixInput]


class WorstPairOut(BaseModel):
    item_i: str
    item_j: str
    judgment: float
    epsilon: float = Field(..., description="a_ij * w_j / w_i; 1.0 = perfectly consistent (Saaty, 2003).")


class PairwiseResultOut(BaseModel):
    items: list[str]
    matrix: list[list[float]]
    eigenvector_weights: list[float] = Field(..., description="Primary: exact eigenvector method (Saaty, 1980).")
    approximate_weights: list[float] = Field(..., description="Diagnostic only, not used downstream (Jensen, 1984).")
    lambda_max: float
    consistency_index: float
    random_index: float
    consistency_ratio: float
    consistent: bool = Field(..., description="True iff consistency_ratio < 0.10.")
    worst_pairs: list[WorstPairOut] = Field(default_factory=list)

    @classmethod
    def from_result(cls, result: PairwiseResult) -> "PairwiseResultOut":
        return cls(
            items=result.items,
            matrix=result.matrix,
            eigenvector_weights=result.eigenvector_weights,
            approximate_weights=result.approximate_weights,
            lambda_max=result.lambda_max,
            consistency_index=result.consistency_index,
            random_index=result.random_index,
            consistency_ratio=result.consistency_ratio,
            consistent=result.consistent,
            worst_pairs=[
                WorstPairOut(item_i=p.item_i, item_j=p.item_j, judgment=p.judgment, epsilon=p.epsilon)
                for p in result.worst_pairs
            ],
        )


class AHPComputeResponse(BaseModel):
    cluster_comparison: PairwiseResultOut
    within_cluster_comparisons: dict[str, PairwiseResultOut]
    final_weights: dict[str, float] = Field(
        ..., description="criterion_id -> cluster_weight * within_cluster_weight (eigenvector method, both levels)."
    )
    complete: bool = Field(
        ...,
        description=(
            "True iff within_cluster_comparisons covered all 5 canonical clusters, in which case "
            "final_weights sums to 1. False means final_weights is a partial, un-normalized set — "
            "callers must not treat it as final until complete is True."
        ),
    )
    missing_clusters: list[str] = Field(
        default_factory=list,
        description="Canonical clusters with no within_cluster_comparisons entry yet. Empty iff complete is True.",
    )

    @classmethod
    def from_hierarchy_result(cls, result: HierarchyResult) -> "AHPComputeResponse":
        return cls(
            cluster_comparison=PairwiseResultOut.from_result(result.cluster_comparison),
            within_cluster_comparisons={
                name: PairwiseResultOut.from_result(r)
                for name, r in result.within_cluster_comparisons.items()
            },
            final_weights=result.final_weights,
            complete=result.complete,
            missing_clusters=result.missing_clusters,
        )
