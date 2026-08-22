"""Maps a criterion's declared `source` name to the function that
produces its raw, not-yet-reclassified physical layer — a small,
explicit, PLUGGABLE registry: `register_source(name, fn)` maps a source
name to a `(AOI) -> (raw_array, grid, nodata, attribution, warning)`
function, and `resolve_criterion_raster` looks a criterion's declared
`source` up in that registry, then applies its `reclassification_rules`
(via Phase 2's cached reclassification). This module's own code never
changes based on how many sources are registered or what any one of
them's internal preprocessing looks like —
dem_elevation/dem_slope/worldcover_land_cover (Phase 2) and
dist_to_river/dist_to_road/twi/drainage_density (this phase) are all
registered exactly the same way, below.

`warning` (the 5th element) is `str | None` — `None` for the overwhelming
majority of sources, which have nothing to flag. It exists for a source
whose result quality genuinely depends on something the caller should
know about (e.g. hydrology.py's `twi`/`drainage_density`, computed less
reliably near a plain bbox AOI's own edges than a basin-derived AOI's
true watershed boundary). It's not a special case in this registry's own
interface — every source returns the same 5-tuple shape, most simply
returning `None` — and it flows straight through to the API response as
its own field (`OverlayComputeResponse.source_warnings`), never folded
into `attribution` (which always stays the plain, unmodified source
citation).

--- Adding a new criterion source (a future 5th, 6th, ... Nth — e.g.
rainfall, NDVI) ---

1. Write a function `(aoi: AOI) -> tuple[np.ndarray, AOIGrid, float, str, str | None]`
   — raw physical values, the common AOIGrid it's on (almost always just
   `compute_aoi_grid(aoi.bounds_utm)`, so it automatically matches every
   other source's grid for the same AOI), its nodata sentinel, its
   attribution string, and an optional warning (`None` unless there's
   something genuinely source-specific to flag) — somewhere in
   app/data/. Give it its own module if it needs real preprocessing of
   its own (like hydrology.py's sink-fill/flow-routing pipeline); a
   couple of lines is enough if it's a thin wrapper around an existing
   app/data/ function (like the `_dem_*` adapters below). Whatever that
   source's own complexity is, it lives entirely inside this function —
   nothing about it should need to leak into this registry or into
   overlay/compute.py's or overlay/service.py's generic pipeline.
2. Decide whether its native values are continuous (elevation, slope,
   distance, TWI, drainage density — bilinear-resampled upstream) or
   categorical (land cover — nearest-neighbor-resampled upstream). This
   determines how the criterion's `reclassification_rules` should be
   shaped (a continuous range-based rule set vs. one rule per discrete
   code, per reclassify.py), but it's entirely the new source function's
   own concern — nothing in this registry inspects or cares which kind
   a given source is.
3. Register it: `register_source("my_new_source", my_new_source_fn)`,
   called anywhere at import time — this module, for a first-party
   source; a test module, for a throwaway one (see
   tests/overlay/test_sources.py's registry-extensibility test, which
   proves this end-to-end using only this public function, from outside
   this module, with zero changes to it).
4. Add a matching `reclassification_rules` array to whatever `Criterion`
   (schemas/criterion.schema.json) declares `source: "my_new_source"`,
   so a POST /api/overlay/compute caller can actually classify it.

Nothing else changes: not resolve_criterion_raster below, not
overlay/compute.py's weighted-sum math, not overlay/service.py's
orchestration (beyond already knowing to look at the 5th tuple element),
not overlay/router.py's endpoint. Every one of those already treats
`source` as an opaque string key it looks up, never interprets itself.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from app.data.aoi import AOI
from app.data.dem import get_dem
from app.data.density_raster import get_building_density
from app.data.distance_raster import get_distance_to_river, get_distance_to_road
from app.data.grid import AOIGrid
from app.data.hydrology import get_drainage_density, get_twi
from app.data.reclassify import apply_reclassification_cached
from app.data.worldcover import get_worldcover

from .errors import OverlayValidationError

SourceFn = Callable[[AOI], tuple[np.ndarray, AOIGrid, float, str, "str | None"]]

_REGISTRY: dict[str, SourceFn] = {}


def register_source(name: str, fn: SourceFn) -> None:
    """Register `fn` under `name`, for resolve_criterion_raster to
    dispatch to whenever a criterion declares `source == name`.

    Raises ValueError if `name` is already registered. Silently
    overwriting an existing registration is far more likely to be a bug
    (a copy-pasted name, an accidental double-import) than an intentional
    hot-swap — this registry has no use case that needs the latter, so
    it isn't supported. Confirmed.
    """
    if name in _REGISTRY:
        raise ValueError(f"criterion source {name!r} is already registered")
    _REGISTRY[name] = fn


def registered_sources() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


# --- built-in sources: each a thin (AOI) -> (array, grid, nodata,
# attribution, warning) adapter around an app/data/ function that does
# the real work (its own local-check/cloud-fallback/preprocessing/
# caching). Only twi/drainage_density ever have a non-None warning. ---


def _dem_elevation(aoi: AOI):
    dem = get_dem(aoi)
    return dem.elevation_m, dem.grid, dem.nodata, dem.attribution, None


def _dem_slope(aoi: AOI):
    dem = get_dem(aoi)
    return dem.slope_degrees, dem.grid, dem.nodata, dem.attribution, None


def _worldcover_land_cover(aoi: AOI):
    wc = get_worldcover(aoi)
    return wc.land_cover_class, wc.grid, wc.nodata, wc.attribution, None


def _dist_to_river(aoi: AOI):
    r = get_distance_to_river(aoi)
    return r.distance_m, r.grid, r.nodata, r.attribution, None


def _dist_to_road(aoi: AOI):
    r = get_distance_to_road(aoi)
    return r.distance_m, r.grid, r.nodata, r.attribution, None


def _twi(aoi: AOI):
    r = get_twi(aoi)
    return r.twi, r.grid, r.nodata, r.attribution, r.warning


def _drainage_density(aoi: AOI):
    r = get_drainage_density(aoi)
    return r.drainage_density, r.grid, r.nodata, r.attribution, r.warning


def _building_density(aoi: AOI):
    r = get_building_density(aoi)
    return r.density, r.grid, r.nodata, r.attribution, None


register_source("dem_elevation", _dem_elevation)
register_source("dem_slope", _dem_slope)
register_source("worldcover_land_cover", _worldcover_land_cover)
register_source("dist_to_river", _dist_to_river)
register_source("dist_to_road", _dist_to_road)
register_source("twi", _twi)
register_source("drainage_density", _drainage_density)
register_source("building_density", _building_density)

# Snapshot at built-in-registration time, for display purposes only (e.g.
# app/overlay/models.py's OverlayCriterionInput.source Field description)
# — a source registered later (e.g. a test's throwaway dummy source)
# won't appear in that already-rendered string, which is fine, since the
# actual enforcement is registered_sources()/the KeyError below, not this
# tuple. Call registered_sources() directly for a live view.
SUPPORTED_SOURCES: tuple[str, ...] = registered_sources()


def _raw_layer_for_source(aoi: AOI, source: str) -> tuple[np.ndarray, AOIGrid, float, str, "str | None"]:
    """Returns (raw_array, grid, nodata, attribution, warning) for one
    registered `source` — the not-yet-reclassified physical layer.
    """
    try:
        fn = _REGISTRY[source]
    except KeyError:
        raise OverlayValidationError(
            f"unrecognized criterion source {source!r}; supported sources are {registered_sources()!r}"
        ) from None
    return fn(aoi)


def resolve_criterion_raster(
    aoi: AOI, criterion_id: str, source: str, reclassification_rules: list[dict]
) -> tuple[np.ndarray, AOIGrid, str, "str | None"]:
    """Fetch the raw physical layer for `source` (via whatever app/data/
    function is registered for it, which handles its own local-check/
    cloud-fallback and AOI-caching) and apply `reclassification_rules`
    (via Phase 2's cached reclassification). Returns (reclassified_array,
    grid, attribution, warning).
    """
    raw, grid, nodata, attribution, warning = _raw_layer_for_source(aoi, source)
    reclassified = apply_reclassification_cached(source, aoi, raw, reclassification_rules, nodata)
    return reclassified, grid, attribution, warning
