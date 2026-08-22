"""Shared DEM-conditioning + D8 flow-routing preprocessing for the two
hydrologically-derived criterion sources (app/overlay/sources.py's `twi`
and `drainage_density` registrations) — the only two sources in this
layer that need more than a "fetch + resample" step before they're ready
to reclassify.

Library choice — pysheds, not richdem (confirmed): both implement the
same class of algorithm this module needs (fill_depressions ~ the
depression-filling approach of Wang & Liu (2006); resolve_flats ~ the
flat-resolution algorithm of Barnes, Lehman & Mulla (2014); D8 flow
direction/accumulation is the standard O'Callaghan & Mark (1984) method
both libraries implement equivalently). richdem's only PyPI distribution
is a compiled C++ extension with prebuilt wheels for Linux/macOS only —
no Windows wheel — which would break `pytest` run from a plain local
Windows environment outside Docker, as this project's is. pysheds ships
a pure-Python/NumPy (`py3-none-any`) wheel, verified during
implementation to install and produce identical, hand-checked results
(see tests/data/test_hydrology.py's synthetic V-valley test) on this
project's Windows dev machine as well as in the Linux Docker image.

One consequence of that choice: pysheds hard-imports `numba` (for its
JIT-compiled inner loops). The version pip resolved for it by default at
implementation time, numba==0.60.0, does not support this project's
pinned `numpy==2.1.2` (`ImportError: Numba needs NumPy 2.0 or less. Got
NumPy 2.1.`) — verified live. requirements.txt therefore pins
`numba>=0.61` explicitly rather than leaving it to pysheds' own
transitive resolution; numba==0.67.0 was verified live to resolve
cleanly against numpy==2.1.2.
"""

from __future__ import annotations

import hashlib
import logging

import numpy as np
import pyproj
from rasterio.features import geometry_mask
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from . import config
from .aoi import AOI, UTM_45N, WGS84
from .attribution import DEM_ATTRIBUTION
from .cache import cached_or_compute
from .dem import SLOPE_OUTPUT_NODATA, compute_slope_degrees, get_dem
from .grid import AOIGrid

logger = logging.getLogger(__name__)

# Shared nodata sentinel for every raster this module produces (flow
# accumulation, TWI, drainage density) — consistent with dem.py's own
# DEM_OUTPUT_NODATA/SLOPE_OUTPUT_NODATA convention (SPEC.md, Nodata
# handling): a value no real computed result can ever land on.
HYDROLOGY_NODATA = -9999.0

# D8 direction codes in the ESRI/pysheds convention: N, NE, E, SE, S,
# SW, W, NW -> 64, 128, 1, 2, 4, 8, 16, 32. Any flowdir() output outside
# this set (0, -1 "flat", -2 "pit") means "no resolved direction here".
_DIRMAP = (64, 128, 1, 2, 4, 8, 16, 32)

# TWI's tan(beta) term is undefined (and ln(alpha / 0) diverges to +inf)
# on a perfectly flat pixel. Floored to this minimum slope (radians)
# before the division, matching the common practical fix in TWI
# implementations (e.g. Quinn et al. 1991; SAGA GIS's own TWI module
# applies an equivalent minimum-slope floor) rather than letting TWI
# blow up to a non-finite, non-rankable value on flat ground. ~0.057
# degrees. Confirmed.
MIN_SLOPE_RADIANS = 0.001

_TO_GRID_CRS = pyproj.Transformer.from_crs(WGS84, UTM_45N, always_xy=True)


def _polygon_inside_mask(polygon: BaseGeometry, grid: AOIGrid) -> np.ndarray:
    """Boolean array, shape (grid.height, grid.width): True for every
    pixel whose center falls inside `polygon` (reprojected from EPSG:4326
    to the grid's own CRS — EPSG:32645, same as UTM_45N by construction).
    """
    polygon_grid_crs = shapely_transform(_TO_GRID_CRS.transform, polygon)
    return geometry_mask(
        [polygon_grid_crs], out_shape=(grid.height, grid.width), transform=grid.transform, invert=True
    )


def _hydrology_cache_version(aoi: AOI) -> str:
    """Cache-key discriminator ensuring a basin-derived AOI (polygon set)
    and a plain bbox AOI that happen to share the same bbox_4326 never
    share a cache entry — they produce genuinely different, non-
    interchangeable flow-accumulation results (see
    _run_pysheds_pipeline's `inside_mask` parameter). AOI.cache_key()
    (cache.py's own per-AOI key) is deliberately bbox-only — see its
    docstring, which flags exactly this ("some consumer actually starts
    using polygon to clip to the true shape") as the trigger to revisit
    that. This module is that consumer, handled here via
    cached_or_compute's `version` parameter (the same mechanism
    reclassify.py uses to version cached output by
    reclassification_rules) rather than by changing cache_key() itself —
    so every other source (dem.py, worldcover.py, osm.py) keeps caching
    exactly as it did before this phase.
    """
    if aoi.polygon is None:
        return "bbox"
    return "polygon_" + hashlib.sha256(aoi.polygon.wkb).hexdigest()[:16]


def _run_pysheds_pipeline(
    elevation: np.ndarray, grid: AOIGrid, dem_nodata: float, inside_mask: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sink-fills `elevation`, then computes D8 flow direction and flow
    accumulation on it. Returns (flow_accumulation, flow_direction,
    valid_mask), all shape (grid.height, grid.width) plain numpy arrays.

    `inside_mask`, when given (a basin-derived AOI), marks every pixel
    OUTSIDE the true polygon boundary as nodata *before* conditioning —
    this is what makes the basin case hydrologically correct: pysheds'
    flow routing then has no data at all to route across the boundary
    from, so a basin's flow accumulation never inflates from ground that
    isn't actually part of that basin. For a plain bbox AOI
    (inside_mask=None), the full rectangular grid is used as-is, and
    accuracy degrades smoothly toward the AOI's own edges — the same
    kind of edge effect dem.py's Horn's-method slope already has, and
    just as much a known, documented limitation rather than a bug.
    """
    from pysheds.grid import Grid as PyshedsGrid
    from pysheds.sview import Raster, ViewFinder

    working = elevation.astype(np.float64).copy()
    own_nodata = working == dem_nodata
    if inside_mask is not None:
        working[~inside_mask] = dem_nodata
    invalid_input = own_nodata | (working == dem_nodata)

    viewfinder = ViewFinder(
        affine=grid.transform, shape=working.shape, nodata=dem_nodata, crs=pyproj.CRS.from_user_input(grid.crs)
    )
    raster = Raster(working, viewfinder=viewfinder)
    pyshed_grid = PyshedsGrid(viewfinder=raster.viewfinder)

    pit_filled = pyshed_grid.fill_pits(raster)
    flooded = pyshed_grid.fill_depressions(pit_filled)
    inflated = pyshed_grid.resolve_flats(flooded)

    fdir_raster = pyshed_grid.flowdir(inflated, dirmap=_DIRMAP, nodata_out=0)
    acc_raster = pyshed_grid.accumulation(fdir_raster, dirmap=_DIRMAP, nodata_out=0.0)

    fdir = np.asarray(fdir_raster)
    acc = np.asarray(acc_raster, dtype=np.float64)

    # Anywhere pysheds couldn't assign one of the 8 real D8 direction
    # codes — the original elevation was nodata, the pixel sits outside
    # a clipped basin polygon, or fill/resolve simply couldn't resolve
    # it (most commonly right at a nodata/edge boundary) — the output is
    # nodata too, never a fabricated 0 or an unexamined pysheds sentinel.
    unresolved = ~np.isin(fdir, _DIRMAP)
    valid = ~(invalid_input | unresolved)

    return acc, fdir, valid


EDGE_RELIABILITY_WARNING = (
    "Computed over this AOI's bounding-box envelope, not a true watershed boundary "
    "(no polygon was supplied) — flow-accumulation-derived values may be underestimated near "
    "the AOI's own edges, since this raster has no way to know what drains in from just "
    "outside it. For an edge-reliable result, use a basin-derived AOI "
    "(GET /api/basins/{hybas_id}/aoi) instead of a hand-drawn bbox."
)


class FlowAccumulationResult:
    def __init__(
        self,
        flow_accumulation: np.ndarray,
        flow_direction: np.ndarray,
        grid: AOIGrid,
        nodata: float,
        valid_mask: np.ndarray,
        clipped_to_polygon: bool,
        attribution: str,
        warning: str | None = None,
    ):
        self.flow_accumulation = flow_accumulation
        self.flow_direction = flow_direction
        self.grid = grid
        self.nodata = nodata
        self.valid_mask = valid_mask
        self.clipped_to_polygon = clipped_to_polygon
        self.attribution = attribution
        self.warning = warning


def compute_flow_accumulation(aoi: AOI) -> FlowAccumulationResult:
    """Sink-filled D8 flow direction + flow accumulation for `aoi`, on
    the same common AOIGrid dem.get_dem(aoi) itself uses (both are pure
    functions of aoi.bounds_utm, so they always match). Cached per-AOI
    like every other app/data/ source, `version`-keyed so a basin AOI
    and a same-bbox plain AOI never collide (see
    _hydrology_cache_version).

    When `aoi.polygon` is set (a basin-derived AOI), the DEM is clipped
    to that true polygon boundary before flow routing — see
    _run_pysheds_pipeline — which is what makes the result hydrologically
    correct rather than just a rectangular approximation. When it's not
    (a plain hand-drawn bbox), `.warning` carries EDGE_RELIABILITY_WARNING
    — plumbed through app/overlay/sources.py's registry contract and
    surfaced to the API caller as its own field
    (OverlayComputeResponse.source_warnings), distinct from `.attribution`
    (which always stays the plain, unmodified source citation).
    """

    def _compute() -> FlowAccumulationResult:
        dem = get_dem(aoi)
        inside_mask = _polygon_inside_mask(aoi.polygon, dem.grid) if aoi.polygon is not None else None
        flow_acc, flow_dir, valid = _run_pysheds_pipeline(dem.elevation_m, dem.grid, dem.nodata, inside_mask)

        clipped = aoi.polygon is not None
        warning = None if clipped else EDGE_RELIABILITY_WARNING

        return FlowAccumulationResult(
            flow_accumulation=flow_acc,
            flow_direction=flow_dir,
            grid=dem.grid,
            nodata=HYDROLOGY_NODATA,
            valid_mask=valid,
            clipped_to_polygon=clipped,
            attribution=DEM_ATTRIBUTION,
            warning=warning,
        )

    return cached_or_compute("hydrology", aoi, _compute, version=_hydrology_cache_version(aoi))


class TWIResult:
    def __init__(self, twi: np.ndarray, grid: AOIGrid, nodata: float, attribution: str, warning: str | None = None):
        self.twi = twi
        self.grid = grid
        self.nodata = nodata
        self.attribution = attribution
        self.warning = warning


def get_twi(aoi: AOI) -> TWIResult:
    """Topographic Wetness Index: TWI = ln(alpha / tan(beta)).

    alpha (specific catchment area) = flow_accumulation_cell_count *
    resolution_m — the standard Moore et al. (1991) convention (upslope
    contributing area divided by contour length, which for a D8 grid
    with single-flow-direction routing is approximated as one cell width
    per contributing cell), confirmed over the brief's own literal
    "flow accumulation x cell area" wording specifically so TWI values
    here are directly comparable to published-literature thresholds
    rather than offset by a constant ln(cell_size) from them.

    beta (local slope) reuses dem.compute_slope_degrees (Horn's method)
    on the AOI's own *unfilled* elevation, per the brief — not the sink-
    filled DEM used for flow routing, since filling artificially
    flattens depressions and would understate the actual local terrain
    slope at that pixel.
    """

    def _compute() -> TWIResult:
        dem = get_dem(aoi)
        flow = compute_flow_accumulation(aoi)

        specific_catchment_area = flow.flow_accumulation * flow.grid.resolution_m

        slope_deg = compute_slope_degrees(dem.elevation_m, dem.grid.resolution_m, dem.nodata)
        slope_rad = np.radians(slope_deg.astype(np.float64))
        slope_rad_floored = np.maximum(slope_rad, MIN_SLOPE_RADIANS)

        twi = np.log(specific_catchment_area / np.tan(slope_rad_floored))

        valid = flow.valid_mask & (dem.elevation_m != dem.nodata) & (slope_deg != SLOPE_OUTPUT_NODATA)
        twi = np.where(valid, twi, HYDROLOGY_NODATA).astype(np.float32)

        return TWIResult(
            twi=twi, grid=flow.grid, nodata=HYDROLOGY_NODATA, attribution=flow.attribution, warning=flow.warning
        )

    return cached_or_compute("twi", aoi, _compute, version=_hydrology_cache_version(aoi))


def compute_drainage_density_raster(
    flow_accumulation: np.ndarray,
    valid_mask: np.ndarray,
    resolution_m: float,
    threshold_cells: int,
    window_radius_m: float,
) -> np.ndarray:
    """Pure function: extracts a synthetic stream network
    (flow_accumulation >= threshold_cells) and turns it into a
    continuous per-pixel drainage-density raster via a circular moving-
    window line-density transform — for each pixel, (total stream length
    within window_radius_m) / (window area), in km per km^2. This is the
    same "Line Density" construction used in the Siraha paper and
    standard GIS tools (e.g. ArcGIS Spatial Analyst's Line Density tool),
    so it can serve as a per-pixel AHP criterion like every other source
    in this registry, rather than a single catchment-wide scalar.

    Each stream pixel is assumed to contribute exactly `resolution_m` of
    stream length (one cell's worth) — a standard raster simplification
    of the true vector stream length threading through that cell (which
    would require tracing actual flow-direction path segments cell by
    cell); at 10m resolution the two are close enough not to matter for
    a risk-ranking use case. Confirmed.
    """
    from scipy.ndimage import convolve

    stream_mask = valid_mask & (flow_accumulation >= threshold_cells)
    stream_length_m = np.where(stream_mask, resolution_m, 0.0)

    radius_px = max(1, round(window_radius_m / resolution_m))
    yy, xx = np.ogrid[-radius_px : radius_px + 1, -radius_px : radius_px + 1]
    kernel = ((xx**2 + yy**2) <= radius_px**2).astype(np.float64)

    window_stream_length_m = convolve(stream_length_m, kernel, mode="constant", cval=0.0)
    window_area_km2 = kernel.sum() * (resolution_m**2) / 1_000_000.0

    density_km_per_km2 = (window_stream_length_m / 1000.0) / window_area_km2
    return density_km_per_km2.astype(np.float32)


class DrainageDensityResult:
    def __init__(
        self,
        drainage_density: np.ndarray,
        grid: AOIGrid,
        nodata: float,
        attribution: str,
        warning: str | None = None,
    ):
        self.drainage_density = drainage_density
        self.grid = grid
        self.nodata = nodata
        self.attribution = attribution
        self.warning = warning


def get_drainage_density(aoi: AOI) -> DrainageDensityResult:
    """Cached wrapper around compute_drainage_density_raster, reading its
    threshold/window-radius parameters from config (dynamically, at call
    time — same convention overlay/service.py uses for
    config.PROCESSED_CACHE_DIR — so tests can monkeypatch them) rather
    than hardcoding either, per the brief. Both are folded into the
    cache version string, so recalibrating either one correctly
    invalidates any stale cached result rather than silently reusing a
    density raster computed under the old settings.
    """

    def _compute() -> DrainageDensityResult:
        flow = compute_flow_accumulation(aoi)
        density = compute_drainage_density_raster(
            flow.flow_accumulation,
            flow.valid_mask,
            flow.grid.resolution_m,
            config.DRAINAGE_DENSITY_THRESHOLD_CELLS,
            config.DRAINAGE_DENSITY_WINDOW_RADIUS_M,
        )
        density = np.where(flow.valid_mask, density, HYDROLOGY_NODATA).astype(np.float32)

        return DrainageDensityResult(
            drainage_density=density,
            grid=flow.grid,
            nodata=HYDROLOGY_NODATA,
            attribution=flow.attribution,
            warning=flow.warning,
        )

    version = (
        f"{_hydrology_cache_version(aoi)}"
        f"_t{config.DRAINAGE_DENSITY_THRESHOLD_CELLS}"
        f"_r{config.DRAINAGE_DENSITY_WINDOW_RADIUS_M}"
    )
    return cached_or_compute("drainage_density", aoi, _compute, version=version)
