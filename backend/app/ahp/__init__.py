"""AHP (Analytic Hierarchy Process) engine: pairwise-matrix priority
computation, two-level cluster/criteria hierarchy composition, and the
POST /api/ahp/compute REST endpoint. See core.py for method citations.
"""

from .core import PairwiseResult, WorstPair, compute_priority_vector
from .errors import AHPConsistencyError, AHPValidationError
from .hierarchy import HierarchyResult, compute_hierarchy
from .router import router

__all__ = [
    "PairwiseResult",
    "WorstPair",
    "compute_priority_vector",
    "AHPConsistencyError",
    "AHPValidationError",
    "HierarchyResult",
    "compute_hierarchy",
    "router",
]
