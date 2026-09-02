"""Real, satellite-observed flood extent polygons -- for validating a
computed risk surface against actual ground truth, a fundamentally
different role from every criterion source registered in
overlay/sources.py (all of which feed the risk surface itself; this
data never does, and is never registered as a criterion).

This is also methodologically distinct from using METEOR's own modeled
flood hazard as either a criterion or a validation reference (see this
project's own discussion on that): METEOR is itself a model's output,
so comparing FloodHUB's computed surface against it only checks
agreement between two models. This module instead reads a real
satellite-detected flood extent -- an actual historical event, not
another model's estimate.

Local-only, no cloud fallback, same reasoning as basins.py/
meteor_flood.py: no live windowed-read endpoint exists for any of these
event-specific products -- each is a one-time downloaded rapid-mapping
deliverable. See config.py's VALIDATION_EVENTS for the registered
events, their sources, and (critically) their real geographic
coverage -- not every event covers this project's Kathmandu Valley
study area, and that's stated explicitly per event rather than left for
a caller to assume from a dataset's own title (config.py's own comment
on `nepal_2024_terai` documents a real case where the title was
misleading: named for "the Capital city of Kathmandu" but its actual
geometry never reaches Kathmandu Valley).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import rasterize

from . import config
from .aoi import AOI
from .cache import cached_or_compute
from .errors import DataSourceUnavailableError
from .grid import AOIGrid, compute_aoi_grid

logger = logging.getLogger(__name__)

# Simplification tolerance (degrees) for the GeoJSON this module serves
# for *map display* (get_validation_extent_geojson, below) -- NOT used
# anywhere in the actual validation math (get_observed_flood_mask reads
# the raw, unsimplified shapefile directly). ~0.0001 deg is ~11m at this
# latitude, matching -- not arbitrary -- the project's own 10m analysis
# grid resolution (grid.py's RESOLUTION_M): simplifying a display copy
# below the resolution the validation itself actually operates at loses
# no information that would ever show up in a computed result, while
# cutting real payload size live-verified during implementation (the
# real nepal_2024_terai polygon, 2084 parts: 9.75MB geometry-only at
# full precision, 2.47MB simplified to this tolerance).
EXTENT_DISPLAY_SIMPLIFY_TOLERANCE_DEG = 0.0001


def _resolve_event_paths(meta: dict) -> list[Path]:
    """`meta["path"]` is normally a single filename (relative to
    config.LOCAL_VALIDATION_EXTENTS_DIR), but an event can also register
    a LIST of filenames -- e.g. nepal_2026_emsr927, delivered by
    Copernicus EMS as 3 separate per-AOI shapefiles but registered here
    as ONE toggleable event, at explicit request, rather than 3 near-
    identical event keys a user would have to pick between one at a
    time. Both call sites below (get_observed_flood_mask,
    get_validation_extent_geojson) go through this + _read_and_merge so
    neither has to special-case "one file" vs "several".
    """
    raw = meta["path"]
    names = raw if isinstance(raw, list) else [raw]
    return [config.LOCAL_VALIDATION_EXTENTS_DIR / name for name in names]


def _read_and_merge(paths: list[Path], target_crs: str) -> gpd.GeoDataFrame:
    """Reads every shapefile in `paths` and merges them into one
    GeoDataFrame in `target_crs`. Each file is reprojected
    INDEPENDENTLY before merging -- never assuming every path in a
    multi-file event shares one native CRS, since this project's other
    events already don't (nepal_2024_west_mbrsc is EPSG:32644,
    rasuwa_2026 is EPSG:32645) -- so a future multi-file event mixing
    native CRSs is handled correctly by construction, not by accident.
    """
    frames = []
    for path in paths:
        gdf = gpd.read_file(path)
        if gdf.crs is not None and str(gdf.crs) != target_crs:
            gdf = gdf.to_crs(target_crs)
        frames.append(gdf)
    if len(frames) == 1:
        return frames[0]
    # ignore_index=True: each source file's own row index is meaningless
    # once merged, and would otherwise produce duplicate index values
    # across files.
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=target_crs)


def _raise_if_missing(event: str, paths: list[Path]) -> None:
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise DataSourceUnavailableError(
            f"validation_extent: no local flood-extent shapefile for event {event!r} -- missing "
            f"{[str(p) for p in missing]} (of {len(paths)} file(s) this event is registered "
            "against). There is no cloud fallback for this one-time downloaded product. See "
            "config.py's VALIDATION_EVENTS for where to obtain it."
        )


def list_validation_events() -> dict[str, str]:
    """{event_key: label} for every registered event -- for an API
    caller (or a future frontend selector) to list what's available
    without needing to know config.VALIDATION_EVENTS' own shape.
    """
    return {key: meta["label"] for key, meta in config.VALIDATION_EVENTS.items()}


class ObservedFloodMaskResult:
    def __init__(self, observed_flooded: np.ndarray, grid: AOIGrid, attribution: str, event: str, label: str):
        # uint8, 1 = observed flooded, 0 = not -- never a third "unknown"
        # value: unlike every criterion source in this package, there is
        # no nodata concept here. A real satellite pass either detected
        # water at a pixel or it didn't; a pixel outside the analysed
        # swath is legitimately "not detected as flooded", not "unknown"
        # (the same reasoning meteor_flood.py's own -9999 fix already
        # applies: not every absence of a positive detection is missing
        # data). Compute_success_rate_curve still restricts its own
        # comparison to pixels the risk surface itself has real data
        # for, so this doesn't overstate "no flooding" beyond what the
        # risk surface can actually be checked against.
        self.observed_flooded = observed_flooded
        self.grid = grid
        self.attribution = attribution
        self.event = event
        self.label = label


def get_observed_flood_mask(aoi: AOI, event: str) -> ObservedFloodMaskResult:
    """Rasterize the named validation event's real flood-extent polygon
    onto `aoi`'s own analysis grid (the exact same `compute_aoi_grid`
    every criterion source uses, so this always lines up pixel-for-pixel
    with a risk surface computed for the same AOI -- no reprojection or
    resampling needed downstream).

    Raises DataSourceUnavailableError if `event` isn't registered, or
    its shapefile isn't present locally (there is no cloud fallback for
    any of these one-time downloaded products).
    """

    def _compute() -> ObservedFloodMaskResult:
        meta = config.VALIDATION_EVENTS.get(event)
        if meta is None:
            raise DataSourceUnavailableError(
                f"validation_extent: unrecognized event {event!r}; registered events are "
                f"{sorted(config.VALIDATION_EVENTS)!r}"
            )

        paths = _resolve_event_paths(meta)
        _raise_if_missing(event, paths)

        logger.info("validation_extent: LOCAL HIT for event=%s aoi=%s -> %s", event, aoi.bbox_4326, paths)
        grid = compute_aoi_grid(aoi.bounds_utm)
        gdf = _read_and_merge(paths, grid.crs)

        geoms = [geom for geom in gdf.geometry if geom is not None and not geom.is_empty]
        if not geoms:
            observed_flooded = np.zeros((grid.height, grid.width), dtype=np.uint8)
        else:
            # all_touched=False -- this is area/polygon coverage (like
            # density_raster.py's own building-footprint rasterization),
            # not a thin line feature (distance_raster.py's
            # all_touched=True case): a pixel only merely clipped by a
            # flood polygon's edge shouldn't count as "observed flooded"
            # any more than a pixel merely clipped by a building
            # footprint counts as "covered" there.
            observed_flooded = rasterize(
                ((geom, 1) for geom in geoms),
                out_shape=(grid.height, grid.width),
                transform=grid.transform,
                fill=0,
                all_touched=False,
                dtype=np.uint8,
            )

        return ObservedFloodMaskResult(
            observed_flooded=observed_flooded, grid=grid, attribution=meta["attribution"], event=event, label=meta["label"]
        )

    # cached_or_compute uses source_name as a literal cache-directory
    # name (cache.py: `config.PROCESSED_CACHE_DIR / source_name`) -- a
    # colon there would break on Windows filesystems, so this is joined
    # with an underscore, not the `module:event`-style separator used
    # elsewhere in this codebase for purely-in-memory keys.
    return cached_or_compute(f"validation_extent_{event}", aoi, _compute)


@lru_cache(maxsize=16)
def get_validation_extent_geojson(event: str) -> dict:
    """The named event's real flood-extent polygon as a plain GeoJSON
    FeatureCollection dict, ready to hand straight to a MapLibre GeoJSON
    source for map display -- the reference-overlay counterpart to
    get_observed_flood_mask's own AOI-rasterized validation-math use of
    the same underlying file (see this module's own docstring for why
    the two are architecturally separate: one is what the map shows, the
    other is what the actual AUC number is computed from).

    Geometry-only (no attribute columns) and simplified to
    EXTENT_DISPLAY_SIMPLIFY_TOLERANCE_DEG for display -- the raw
    shapefile's own attribute table isn't just unnecessary here, one of
    its columns (a datetime field) isn't even JSON-serializable via
    geopandas' own to_json() without being dropped or converted first
    (confirmed live during implementation), so dropping every column but
    geometry sidesteps that rather than working around it column by
    column.

    lru_cache, not cached_or_compute: this has no AOI to key by at all
    (unlike every other cache in this package) -- it's the same static
    result for the whole process lifetime, the same "bounded in-process
    cache" pattern osm.py's own local .pbf parser cache already
    establishes (reset_local_osm_parser_cache there; there is
    deliberately no equivalent reset function here, since nothing in
    this package ever mutates a validation event's source file at
    runtime the way a test suite's own local-source monkeypatching would
    need to account for -- tests exercise this function directly against
    their own fixtures instead).

    Raises DataSourceUnavailableError, same as get_observed_flood_mask,
    for an unrecognized event or a missing local file.
    """
    meta = config.VALIDATION_EVENTS.get(event)
    if meta is None:
        raise DataSourceUnavailableError(
            f"validation_extent: unrecognized event {event!r}; registered events are "
            f"{sorted(config.VALIDATION_EVENTS)!r}"
        )

    paths = _resolve_event_paths(meta)
    _raise_if_missing(event, paths)

    logger.info("validation_extent: building display GeoJSON for event=%s -> %s", event, paths)
    gdf = _read_and_merge(paths, "EPSG:4326")

    simplified = gdf.geometry.simplify(EXTENT_DISPLAY_SIMPLIFY_TOLERANCE_DEG)
    geom_only = gpd.GeoDataFrame(geometry=simplified, crs="EPSG:4326")
    return json.loads(geom_only.to_json())
