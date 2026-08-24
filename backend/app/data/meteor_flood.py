"""METEOR Project Nepal flood hazard source: modeled water depth (meters)
from the Fathom global flood hazard framework -- local-only, unlike
every other module in this package. There is no live cloud fallback
here: METEOR only exposes raw numeric depth values through a one-time
downloadable GeoTIFF package, not through any windowed-read-friendly
endpoint the way dem.py/worldcover.py/soil.py/chirps.py's cloud
fallbacks do (their public WMS/WMTS tile service serves pre-styled RGB
PNG only, useless as numeric criterion input -- verified live during
implementation). A missing local file is therefore a hard failure here
(DataSourceUnavailableError), not the normal "fall back to cloud" case
every local-check-first module in this package treats it as.

This is also a genuinely different *kind* of criterion from every other
source registered in overlay/sources.py: it isn't a proxy correlated
with flood risk (distance to river, TWI, HAND, rainfall, ...) -- it's a
third party's own modeled flood hazard output, i.e. someone else's
answer to the same question this project's AHP pipeline is built to
compute. Registered anyway, at explicit request, as one input among
several rather than a replacement for the others: METEOR/Fathom's own
metadata.txt is explicit that "it is not recommended to use the data
for detailed local scale assessments or engineering purposes" given its
~90m/regional-scale modelling assumptions.

--- Sentinel handling: -9999 becomes a real depth of 0.0, not nodata ---

The very first version of this module masked both empirically-found
sentinels (-9999.0 "outside the Fathom model's simulated floodplain
domain", 999.0 a much rarer masked value) to nodata, excluded from
reclassification entirely. Real problem reported by the user after
using it: "only the meteor area gets flood hazard output" -- since
-9999.0 covers ~97% of a typical AOI (confirmed live against the real
FD_1in100.tif; see config.py's own comment), the composite risk surface
ended up with almost no classified area at all wherever this criterion
was included, everywhere outside the narrow modeled floodplain.

Fixed per the user's explicit instruction ("make it so that the nodata
in meteor is 0 and all the aoi gets hazard classification") -- and this
is a scientifically defensible reinterpretation, not just a literal
"nodata equals zero" hack: metadata.txt's own documented semantics say
-9999 pixels are ones the model deliberately never attempts to flood
(hillslope/ridge terrain outside any floodplain), which for a *flood
hazard* criterion genuinely does mean "no flood hazard from this source
at this location" -- a real, known value, not an unknown one. This
follows the same reasoning soil.py's own docstring already applies in
the opposite direction: SoilGrids' nodata is kept as nodata specifically
because "no equivalent documented reason was found" to remap it to a
particular value; here, METEOR's own documentation supplies exactly
that reason, so remapping is the documented-reason case that module was
contrasting itself against, not an exception to this project's nodata
discipline.

999.0 (the rarer sentinel) is NOT also mapped to 0 -- unlike -9999, it
does not mean "no hazard"; it's a masked/permanent-water flag (per
METEOR's own legend graphic, "Permanent" is its own category, ranked
above the 5m class, not below it). Mapping it to 0 would misclassify
permanent water as the lowest-risk case, a real correctness bug the
user's literal instruction doesn't actually ask for once its intent
("every pixel gets a real classification, driven by what METEOR
actually models there") is followed through consistently. It maps
instead to `_PERMANENT_WATER_DEPTH_M` (5.0, this file's own observed
maximum real modeled depth), landing in the same top risk_class as the
worst real modeled cells.

Net effect: every pixel in the analysis grid now gets a real depth
value (0.0, a real modeled depth, or 5.0), and METEOR_FLOOD_OUTPUT_NODATA
is in practice unreachable -- kept declared anyway (passed to
reproject_to_grid's dst_nodata, guarded by require_defined_nodata) only
because SPEC.md's nodata-handling convention requires every output to
declare one explicitly, per nodata.py's own docstring, not because this
module expects to ever actually emit it. The low-in-domain-coverage
`.warning` the first version attached is gone along with it -- there is
no coverage gap left to warn about; DATA_GAP_DISCLAIMERS' own
flood_hazard_meteor entry was removed from config/criteria.js for the
same reason.

See attribution.py's METEOR_FLOOD_ATTRIBUTION for the full citation and
config.py's LOCAL_METEOR_FLOOD_DIR comment for the live-verified file
format (CRS, dtype, both sentinel values, and real value range).
"""

from __future__ import annotations

import logging
import math

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds

from . import config
from .aoi import AOI
from .attribution import METEOR_FLOOD_ATTRIBUTION
from .cache import cached_or_compute
from .errors import DataSourceUnavailableError
from .grid import AOIGrid, compute_aoi_grid, reproject_to_grid
from .local_source import find_local_raster_covering_aoi
from .nodata import require_defined_nodata

logger = logging.getLogger(__name__)

METEOR_FLOOD_OUTPUT_NODATA = -9999.0

# Depth (m) assigned to the rarer 999.0 sentinel -- this file's own
# observed maximum real modeled depth (FD_1in100.tif, live-verified
# during implementation: real values range 0.0-5.0m), so a permanent-
# water/masked cell lands in the same top risk_class as the worst real
# modeled cells rather than being misread as "no hazard." See this
# module's own docstring for why 999 gets this treatment while -9999
# gets 0.0 instead, not the same treatment.
_PERMANENT_WATER_DEPTH_M = 5.0


# Extra whole source pixels of margin _whole_pixel_window reads beyond
# the AOI's own bounds on every side -- a second, real bug caught live
# only after the sentinel fix above made it visible: bilinear resampling
# needs real neighboring source data around each destination pixel, and
# a window cropped tightly to the AOI (this function's own first version
# below) starves the destination grid's edge pixels of that neighbor
# data, leaving them at dst_nodata regardless of what the sentinels
# resolve to. Confirmed live against the real FD_1in100.tif over three
# real AOIs (a Kathmandu floodplain bbox, a Shivapuri hillslope bbox, and
# a small ~500m tight bbox): 1px of margin got a floodplain AOI to
# 99.9% valid (a residual handful of pixels still at dst_nodata, mean
# depth dragged to roughly -5m by them); 2px reached the full 100% on
# all three. METEOR's own ~90m native pixels make this margin matter far
# more than it would for DEM (30m)/WorldCover (10m)'s own unbuffered
# from_bounds windows -- proportionally, a 90m fringe is a much bigger
# slice of a typical AOI than a 30m or 10m one is, which is also why
# this went unnoticed before: previously -9999 pixels were ALL treated
# as nodata regardless of cause, so a few extra edge-margin nodata
# pixels were invisible against the ~97% domain-sentinel nodata already
# present.
_WINDOW_MARGIN_PX = 2


def _whole_pixel_window(aoi: AOI, transform) -> Window:
    """Same defensive expansion as chirps.py's own `_whole_pixel_window`
    (see that module's docstring for the real sub-pixel-window bug this
    guards against) -- METEOR's ~90m native pixels are coarser than
    DEM/WorldCover/SoilGrids, so a small polygon-drawn AOI could in
    principle still fall inside a single pixel's footprint -- PLUS an
    extra `_WINDOW_MARGIN_PX`-pixel margin on every side beyond the
    whole-pixel rounding itself (see that constant's own comment for the
    real bug this closes). Margin is clamped at 0 so a window can never
    start before the dataset's own origin; the far/high edge is left
    unclamped against the dataset's width/height, since `ds.read()` on a
    window that extends slightly past a raster's own bounds already
    behaves safely today (this project's other windowed reads --
    dem.py/chirps.py's own `_read_local_window` -- rely on the same
    property, unbuffered).
    """
    window = from_bounds(*aoi.bbox_4326, transform=transform)
    col_off = max(0, math.floor(window.col_off) - _WINDOW_MARGIN_PX)
    row_off = max(0, math.floor(window.row_off) - _WINDOW_MARGIN_PX)
    col_end = math.ceil(window.col_off + window.width) + _WINDOW_MARGIN_PX
    row_end = math.ceil(window.row_off + window.height) + _WINDOW_MARGIN_PX
    width = max(1, col_end - col_off)
    height = max(1, row_end - row_off)
    return Window(col_off, row_off, width, height)


class MeteorFloodResult:
    def __init__(
        self,
        depth_m: np.ndarray,
        grid: AOIGrid,
        nodata: float,
        source_used: str,
        warning: str | None,
    ):
        self.depth_m = depth_m
        self.grid = grid
        self.nodata = nodata
        self.source_used = source_used
        self.warning = warning
        self.attribution = METEOR_FLOOD_ATTRIBUTION


def _resolve_sentinels(raw: np.ndarray) -> np.ndarray:
    """Both empirically-found raw sentinel values (config.py's
    METEOR_FLOOD_RAW_SENTINELS) become real depth values, not nodata --
    see this module's own docstring for the full rationale. -9999
    ("outside the model's simulated floodplain domain") becomes 0.0m
    (no flood hazard from this source here); 999 (the rarer masked/
    permanent-water value) becomes `_PERMANENT_WATER_DEPTH_M`, NOT 0 --
    the two sentinels mean different things physically and are
    deliberately NOT treated the same.
    """
    outside_domain, permanent_water = config.METEOR_FLOOD_RAW_SENTINELS
    depth = raw.astype(np.float64)
    depth[raw == outside_domain] = 0.0
    depth[raw == permanent_water] = _PERMANENT_WATER_DEPTH_M
    return depth


def _read_local_window(path, aoi: AOI):
    with rasterio.open(path) as ds:
        window = _whole_pixel_window(aoi, ds.transform)
        data = ds.read(1, window=window)
        window_transform = ds.window_transform(window)
        crs = ds.crs
    return data, window_transform, crs


def get_meteor_flood_hazard(aoi: AOI) -> MeteorFloodResult:
    def _compute() -> MeteorFloodResult:
        filename = f"{config.METEOR_FLOOD_TYPE}_{config.METEOR_FLOOD_RETURN_PERIOD}.tif"
        match = find_local_raster_covering_aoi(config.LOCAL_METEOR_FLOOD_DIR, aoi, patterns=(filename,))
        if match is None:
            raise DataSourceUnavailableError(
                f"meteor_flood: no local {filename!r} covering this AOI found in "
                f"{config.LOCAL_METEOR_FLOOD_DIR} -- there is no live cloud fallback for METEOR's "
                "raw numeric flood-depth values (only pre-styled WMS/WMTS tiles exist publicly, "
                "unsuitable as criterion input; see this module's own docstring). Download the "
                "flood hazard package from https://maps.meteor-project.org/map/flood-npl/download "
                f"and place the wanted layer at {config.LOCAL_METEOR_FLOOD_DIR / filename} (see "
                "app/data/config.py's LOCAL_METEOR_FLOOD_DIR comment for the naming convention)."
            )

        logger.info("meteor_flood: LOCAL HIT for aoi=%s -> %s", aoi.bbox_4326, match.path)
        array, transform, crs = _read_local_window(match.path, aoi)
        source_used = f"local:{match.path.name}"

        # Both raw sentinels are resolved to real depth values BEFORE
        # reprojection (see _resolve_sentinels' own docstring) -- there is
        # no remaining "nodata" concept in the source array by the time
        # it reaches reproject_to_grid, so src_nodata=None: every pixel is
        # real data, and bilinear-blending across a former sentinel
        # boundary (e.g. 0.0m next to a real 0.3m) is now genuinely
        # meaningful interpolation, not a masking artifact to guard
        # against.
        depth_native = _resolve_sentinels(array)

        grid = compute_aoi_grid(aoi.bounds_utm)
        depth_resampled = reproject_to_grid(
            depth_native, transform, crs, grid,
            kind="continuous", src_nodata=None, dst_nodata=METEOR_FLOOD_OUTPUT_NODATA, dtype=np.float32,
        )
        nodata = require_defined_nodata(METEOR_FLOOD_OUTPUT_NODATA, "flood_hazard_meteor")

        # No coverage-gap warning any more (see this module's own
        # docstring) -- every pixel this reprojection could possibly
        # produce is real data now, so there is nothing left to warn
        # about. dst_nodata above exists only to satisfy
        # require_defined_nodata/SPEC.md's nodata-handling convention for
        # the one theoretical case reproject_to_grid itself could still
        # produce it (an AOI extending beyond this GeoTIFF's own raster
        # bounds entirely, which -- since it covers all of Nepal -- this
        # app's real AOIs never do in practice).
        return MeteorFloodResult(
            depth_m=depth_resampled, grid=grid, nodata=nodata, source_used=source_used, warning=None
        )

    return cached_or_compute("flood_hazard_meteor", aoi, _compute)
