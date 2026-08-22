"""HydroBASINS Asia level-8 basin polygons: lookup by HYBAS_ID, listing
basins overlapping Nepal, support-status classification, and
basin_to_aoi() — the bridge from a selected basin into the existing AOI
pipeline (aoi.py), so DEM/WorldCover fetch, reclassification, and the
overlay engine all keep working completely unchanged (they only ever
read AOI.bbox_4326 / AOI.bounds_utm, which basin_to_aoi populates from
the basin's own bounding envelope).

Expects config.LOCAL_BASINS_PATH to be a HydroBASINS "Standard" (polygon)
shapefile — HYBAS_ID + Polygon/MultiPolygon geometry. Download the Asia
("as") region, level 08, "Standard" format from
https://www.hydrosheds.org/products/hydrobasins.

IMPORTANT: this is NOT the same as HydroBASINS' "Pour Points" product
(filenames like hybas_pour_lev08_v1.shp), which is a global table of
POINT geometries marking basin outlets — it cannot represent a basin
boundary and _validate_basins_schema below will reject it with a clear
error identifying exactly this mismatch, rather than silently trying to
compute polygon operations on point geometry.

Optionally also uses config.LOCAL_NEPAL_BOUNDARY_PATH — Nepal's true
country boundary (ADM0) — for a more accurate support-status
classification than the NEPAL_BBOX_4326 rectangle proxy. This file is
genuinely optional: if it's absent, classification falls back to the
proxy automatically (with a one-time logged warning), never an error.
Source used during implementation: HERMES (https://download.hermes.com.np),
whose license permits NON-COMMERCIAL USE ONLY and prohibits
redistribution without consent — this repo never commits it
(backend/data/raw/ is gitignored); swap in a commercially-usable source
(e.g. OCHA/HDX, Natural Earth) before any commercial deployment.
"""

from __future__ import annotations

import logging

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from . import config
from .aoi import AOI
from .errors import BasinNotFoundError, DataSourceUnavailableError

logger = logging.getLogger(__name__)

_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)

# A rough, deliberately generous screening box around Nepal — used (a) to
# decide which basins are even worth listing at GET /api/basins ("rough
# bounding filter, not a hard restriction — cross-border basins are
# kept"), always, regardless of whether the true boundary (below) is
# available, and (b) as the *fallback* proxy region for the support-status
# area-percentage classification, only when config.LOCAL_NEPAL_BOUNDARY_PATH
# isn't available — the true boundary is preferred whenever it's present.
NEPAL_BBOX_4326 = (80.0, 26.3, 88.3, 30.5)

# Support-status thresholds: the fraction of a basin's own true area that
# falls within Nepal's true boundary (or, absent that file, NEPAL_BBOX_4326).
#   >= 98%        -> "fully_in_nepal": for practical purposes the whole
#                    basin is inside Nepal; edge effects are negligible.
#   >= 50%, < 98%  -> "partial_likely_adequate": most of the basin's area
#                    (and therefore most of its hydrology) is in Nepal;
#                    Copernicus/WorldCover data itself is available
#                    globally so there's no raw *data* gap at the border,
#                    but a meaningful share of the basin's upstream
#                    drainage lies outside the analysis's usual frame of
#                    reference, so results should be read as reasonable
#                    but not as tight as a fully-contained basin.
#   < 50%          -> "likely_degraded_at_edges": most of the basin is
#                    outside Nepal; a Nepal-focused flood-risk analysis
#                    is missing the majority of this basin's own
#                    catchment and should be treated with low confidence.
# These thresholds are a judgment call (not derived from any external
# standard) — flagged explicitly for confirmation.
FULLY_IN_NEPAL_THRESHOLD = 0.98
PARTIAL_ADEQUATE_THRESHOLD = 0.50

SUPPORT_STATUS_FULLY_IN_NEPAL = "fully_in_nepal"
SUPPORT_STATUS_PARTIAL_ADEQUATE = "partial_likely_adequate"
SUPPORT_STATUS_DEGRADED = "likely_degraded_at_edges"

_basins_gdf: gpd.GeoDataFrame | None = None
_nepal_boundary_load_attempted = False
_nepal_reference_geom_utm: BaseGeometry | None = None

# Per-HYBAS_ID cache for classify_support_status/pct_area_in_nepal
# results — a basin's geometry never changes during process lifetime, so
# once computed for a given HYBAS_ID (against the currently-loaded basins
# file and Nepal reference geometry) the result is valid until either of
# those change, which reset_basins_cache()/reset_nepal_boundary_cache()
# both account for. Motivated by GET /api/basins classifying every listed
# basin (hundreds, for the real HydroBASINS dataset) on every request —
# measured at ~3s for the real ~547-basin Nepal-overlap set on a cold
# cache; this makes every request after the first for the same set of
# basins effectively free.
_support_status_cache: dict[int, str] = {}
_pct_in_nepal_cache: dict[int, float] = {}


def _to_utm_geom(geom: BaseGeometry) -> BaseGeometry:
    return shapely_transform(_TO_UTM.transform, geom)


def _validate_basins_schema(gdf: gpd.GeoDataFrame, path) -> None:
    if "HYBAS_ID" not in gdf.columns:
        raise DataSourceUnavailableError(
            f"basins: {path} has no HYBAS_ID column; is this really the HydroBASINS "
            "'Standard' polygon product? See app/data/basins.py's module docstring."
        )
    geom_types = set(gdf.geom_type.unique())
    if not geom_types <= {"Polygon", "MultiPolygon"}:
        raise DataSourceUnavailableError(
            f"basins: {path} contains {sorted(geom_types)} geometry, not Polygon/MultiPolygon. "
            "This looks like the HydroBASINS 'Pour Points' product (point geometry marking basin "
            "outlets), not the basin-boundary 'Standard' product this module needs — download the "
            "Asia ('as') region, level 08, 'Standard' format from "
            "https://www.hydrosheds.org/products/hydrobasins instead."
        )


def _load_basins() -> gpd.GeoDataFrame:
    global _basins_gdf
    if _basins_gdf is not None:
        return _basins_gdf

    path = config.LOCAL_BASINS_PATH
    if not path.exists():
        raise DataSourceUnavailableError(
            f"basins: no HydroBASINS file at {path}. Download the Asia ('as') region, level 08, "
            "'Standard' (polygon) format from https://www.hydrosheds.org/products/hydrobasins and "
            "place it there, or set BASINS_SHAPEFILE_PATH to point at it."
        )

    logger.info("basins: loading HydroBASINS polygons from %s", path)
    gdf = gpd.read_file(path)
    _validate_basins_schema(gdf, path)

    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    gdf["HYBAS_ID"] = gdf["HYBAS_ID"].astype("int64")
    gdf = gdf.set_index("HYBAS_ID", drop=False)

    logger.info("basins: loaded %d basin polygons", len(gdf))
    _basins_gdf = gdf
    return _basins_gdf


def reset_basins_cache() -> None:
    """Test-only: drop the in-memory cache so a subsequent call to
    _load_basins() re-reads from (a possibly newly-monkeypatched)
    config.LOCAL_BASINS_PATH instead of reusing whatever was loaded by an
    earlier test. Also clears the per-HYBAS_ID classification cache below,
    since a different basins file can change what a given HYBAS_ID even
    refers to.
    """
    global _basins_gdf
    _basins_gdf = None
    _support_status_cache.clear()
    _pct_in_nepal_cache.clear()


def reset_nepal_boundary_cache() -> None:
    """Test-only: mirrors reset_basins_cache() for the Nepal boundary
    reference geometry. Also clears the per-HYBAS_ID classification
    cache, since it's a function of both the basin's geometry and the
    Nepal reference geometry.
    """
    global _nepal_boundary_load_attempted, _nepal_reference_geom_utm
    _nepal_boundary_load_attempted = False
    _nepal_reference_geom_utm = None
    _support_status_cache.clear()
    _pct_in_nepal_cache.clear()


def _load_nepal_reference_geom_utm() -> BaseGeometry:
    """Nepal's true country boundary (ADM0), reprojected to EPSG:32645 and
    cached — computed once, not once per basin classified, since
    GET /api/basins classifies every listed basin (hundreds, for the real
    HydroBASINS dataset) in one request. Falls back to the NEPAL_BBOX_4326
    rectangle proxy, with a one-time logged warning, if
    config.LOCAL_NEPAL_BOUNDARY_PATH isn't available — this dataset is
    optional, unlike the basins file itself.
    """
    global _nepal_boundary_load_attempted, _nepal_reference_geom_utm
    if _nepal_reference_geom_utm is not None:
        return _nepal_reference_geom_utm

    geom_4326: BaseGeometry | None = None
    path = config.LOCAL_NEPAL_BOUNDARY_PATH
    if path.exists():
        logger.info("basins: loading Nepal country boundary from %s", path)
        gdf = gpd.read_file(path)
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
        geom_4326 = gdf.geometry.union_all() if len(gdf) > 1 else gdf.geometry.iloc[0]
    elif not _nepal_boundary_load_attempted:
        logger.warning(
            "basins: no Nepal boundary file at %s; falling back to the rough NEPAL_BBOX_4326 "
            "rectangle proxy for support-status classification (less accurate at the edges)",
            path,
        )

    _nepal_boundary_load_attempted = True
    _nepal_reference_geom_utm = _to_utm_geom(geom_4326 if geom_4326 is not None else box(*NEPAL_BBOX_4326))
    return _nepal_reference_geom_utm


def basin_area_km2(polygon: BaseGeometry) -> float:
    """`polygon`'s own true area in km², reprojected to EPSG:32645
    (SPEC.md, CRS convention: never compute area directly in degrees).
    """
    return _to_utm_geom(polygon).area / 1_000_000.0


def pct_area_in_nepal(polygon: BaseGeometry) -> float:
    """Fraction (0-1) of `polygon`'s own true area that intersects Nepal's
    true boundary (or, absent that file, the NEPAL_BBOX_4326 rectangle
    proxy), computed in EPSG:32645. 0.0 for a degenerate (zero-area)
    polygon.
    """
    basin_utm = _to_utm_geom(polygon)
    basin_area = basin_utm.area
    if basin_area <= 0:
        return 0.0
    nepal_utm = _load_nepal_reference_geom_utm()
    return basin_utm.intersection(nepal_utm).area / basin_area


def classify_support_status(polygon: BaseGeometry) -> str:
    """fully_in_nepal / partial_likely_adequate / likely_degraded_at_edges
    — see the threshold constants above for the exact cutoffs and the
    reasoning behind them.
    """
    pct = pct_area_in_nepal(polygon)
    if pct >= FULLY_IN_NEPAL_THRESHOLD:
        return SUPPORT_STATUS_FULLY_IN_NEPAL
    if pct >= PARTIAL_ADEQUATE_THRESHOLD:
        return SUPPORT_STATUS_PARTIAL_ADEQUATE
    return SUPPORT_STATUS_DEGRADED


def get_basin_pct_in_nepal(hybas_id: int) -> float:
    """pct_area_in_nepal(basin.geometry) for the basin identified by
    hybas_id, cached — see the module-level cache comment above.
    """
    if hybas_id not in _pct_in_nepal_cache:
        _pct_in_nepal_cache[hybas_id] = pct_area_in_nepal(get_basin(hybas_id).geometry)
    return _pct_in_nepal_cache[hybas_id]


def get_basin_support_status(hybas_id: int) -> str:
    """classify_support_status(basin.geometry) for the basin identified by
    hybas_id, cached — see the module-level cache comment above. This is
    what GET /api/basins and GET /api/basins/{hybas_id} actually call,
    not classify_support_status directly.
    """
    if hybas_id not in _support_status_cache:
        pct = get_basin_pct_in_nepal(hybas_id)  # populates/reuses that cache too
        if pct >= FULLY_IN_NEPAL_THRESHOLD:
            status = SUPPORT_STATUS_FULLY_IN_NEPAL
        elif pct >= PARTIAL_ADEQUATE_THRESHOLD:
            status = SUPPORT_STATUS_PARTIAL_ADEQUATE
        else:
            status = SUPPORT_STATUS_DEGRADED
        _support_status_cache[hybas_id] = status
    return _support_status_cache[hybas_id]


def list_basins_overlapping_nepal() -> gpd.GeoDataFrame:
    """All basins whose geometry intersects NEPAL_BBOX_4326 at all — a
    deliberately generous, rough filter, not a hard restriction:
    cross-border basins are kept in full (their true geometry, not
    clipped to Nepal), per SPEC.md.
    """
    gdf = _load_basins()
    nepal_box = box(*NEPAL_BBOX_4326)
    return gdf[gdf.intersects(nepal_box)]


def get_basin(hybas_id: int):
    """A single basin row (HYBAS_ID + geometry, plus whatever other
    HydroBASINS attribute columns the source file carries). Raises
    BasinNotFoundError if hybas_id isn't in the loaded dataset.
    """
    gdf = _load_basins()
    try:
        row = gdf.loc[hybas_id]
    except KeyError:
        raise BasinNotFoundError(f"no basin with HYBAS_ID={hybas_id}") from None
    # .loc on a non-unique index could return a DataFrame; HYBAS_ID is
    # documented as unique per level, but guard against a malformed
    # source file anyway rather than silently returning the wrong shape.
    if isinstance(row, gpd.GeoDataFrame):
        row = row.iloc[0]
    return row


def basin_to_aoi(hybas_id: int) -> AOI:
    """The bridge from a selected basin to the existing AOI pipeline:
    bbox_4326 is the basin polygon's bounding envelope (derived
    automatically), polygon is the true basin geometry. Every existing
    AOI-consuming function keeps operating on bbox_4326/bounds_utm
    exactly as it does for a hand-drawn bbox AOI.
    """
    basin = get_basin(hybas_id)
    polygon = basin.geometry
    minx, miny, maxx, maxy = polygon.bounds
    return AOI(bbox_4326=(minx, miny, maxx, maxy), polygon=polygon)
