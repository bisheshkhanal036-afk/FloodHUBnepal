"""Nodata handling per SPEC.md's "Nodata handling" convention.

Every source module in this package assigns its own explicit,
canonical output nodata value when it reprojects onto the common grid
(grid.reproject_to_grid's `dst_nodata`) — DEM/slope always use
DEM_OUTPUT_NODATA below, WorldCover always uses WORLDCOVER_OUTPUT_NODATA
— regardless of whatever the raw source file/tile did or didn't declare.
That's a deliberate normalization step, not a pass-through: a source
raster's own nodata metadata is read explicitly where it matters (e.g. as
`src_nodata` during reprojection) but never silently assumed.

Note on Copernicus GLO-30: verified live during implementation that
GLO-30 COG tiles report no nodata tag at all (`rasterio`'s `ds.nodata` is
`None`) — consistent with GLO-30 being a void-filled product with no
missing pixels within a tile. That is a deliberate, verified property of
the source, not an oversight; `_fetch_dem_from_s3` passes `src_nodata=None`
for exactly this reason. ESA WorldCover, by contrast, does declare
nodata=0 on every tile (also verified live) and that value is used as-is.

The functions below are the guardrail against a mismatch ever silently
reaching a caller: every processed result's nodata must be a concrete,
known value before it leaves this package, and (looking ahead to the
overlay-math phase that will combine multiple sources) any place that
combines rasters from more than one of these functions must first check
they agree on what "nodata" means well enough to be combined safely.
"""

from __future__ import annotations

import math

from .errors import NodataValidationError


def require_defined_nodata(nodata, source_name: str) -> float:
    """Guard against a processed output ever leaving this package with an
    undefined nodata value. Every get_*() function in this package always
    assigns an explicit dst_nodata during reprojection, so this should
    never actually trip in normal operation — it exists to fail loudly,
    rather than silently, if a future change to this package's own code
    ever drops that assignment.
    """
    if nodata is None:
        raise NodataValidationError(
            f"{source_name}: processed output has no defined nodata value; "
            "refusing to return raster data with ambiguous nodata"
        )
    return nodata


def assert_consistent_nodata(rasters: dict[str, float]) -> None:
    """Raise if two already-processed rasters that are about to be
    combined (future overlay-math phase) don't agree on a single nodata
    convention. Takes {label: nodata_value}; NaN-aware (NaN != NaN, so a
    naive equality check would always report every pair as inconsistent).
    """
    if len(rasters) < 2:
        return
    values = list(rasters.items())
    label0, nodata0 = values[0]
    for label, nodata in values[1:]:
        both_nan = isinstance(nodata0, float) and isinstance(nodata, float) and math.isnan(nodata0) and math.isnan(nodata)
        if not both_nan and nodata != nodata0:
            raise NodataValidationError(
                f"mismatched nodata across rasters to be combined: "
                f"{label0}={nodata0!r} vs {label}={nodata!r}. "
                "Harmonize nodata before any overlay math (SPEC.md, Nodata handling)."
            )
