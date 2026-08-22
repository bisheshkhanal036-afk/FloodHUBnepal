"""Shared, cross-phase utilities used by more than one API module —
currently just AOI request parsing + area-cap validation (aoi.py).
"""

from .aoi import MAX_AREA_KM2, AOIInput

__all__ = ["AOIInput", "MAX_AREA_KM2"]
