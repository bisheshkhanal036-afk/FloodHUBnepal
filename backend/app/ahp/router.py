"""REST endpoint for the AHP engine."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .errors import AHPConsistencyError, AHPValidationError
from .hierarchy import compute_hierarchy
from .models import AHPComputeRequest, AHPComputeResponse

router = APIRouter(prefix="/api/ahp", tags=["ahp"])


@router.post("/compute", response_model=AHPComputeResponse)
def compute_ahp(payload: AHPComputeRequest) -> AHPComputeResponse:
    """Compute AHP priority weights for the cluster-level matrix and each
    cluster's within-cluster matrix, and compose the final per-criterion
    weights. Returns eigenvector_weights (primary), approximate_weights
    (diagnostic), lambda_max, CI, and CR for every matrix, plus
    final_weights.

    Responds 422 if any matrix is structurally invalid, or if any matrix
    fails the CR < 0.10 consistency check (body includes which judgments
    are least consistent for every failing matrix).
    """
    cluster_comparison = payload.cluster_comparison.model_dump()
    within_cluster_comparisons = {
        name: m.model_dump() for name, m in payload.within_cluster_comparisons.items()
    }
    try:
        result = compute_hierarchy(cluster_comparison, within_cluster_comparisons)
    except AHPConsistencyError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc
    except AHPValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": "ahp_validation_error", "message": str(exc)}) from exc

    return AHPComputeResponse.from_hierarchy_result(result)
