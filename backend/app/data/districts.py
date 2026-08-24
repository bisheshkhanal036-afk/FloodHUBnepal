"""Nepal administrative-district (admin level 2) polygons: lookup by
pcode, listing all districts, and district_to_aoi() — the bridge from a
selected district into the existing AOI pipeline (aoi.py), mirroring
app/data/basins.py's basin_to_aoi() exactly (DEM/WorldCover fetch,
reclassification, the overlay engine all keep working completely
unchanged, since they only ever read AOI.bbox_4326 / AOI.bounds_utm,
which district_to_aoi populates from the district's own bounding
envelope).

Expects config.LOCAL_ADMIN_DISTRICTS_PATH to be the admin-level-2 layer
of OCHA/HDX's "Nepal - Subnational Administrative Boundaries" COD-AB
dataset (https://data.humdata.org/dataset/cod-ab-npl) — the same file
basins.py's LOCAL_NEPAL_BOUNDARY_PATH points its own admin-level-0 layer
at (see that module's docstring for the full source/license writeup:
CC BY-IGO, commercial use and redistribution both permitted). Nepal has
77 districts (adm2_pcode values like "NP0101"); unlike basins, a
district is by definition entirely within Nepal, so there's no
support-status concept here — every district behaves as if
"fully_in_nepal".

No Nepal-bbox screening is needed either (unlike
basins.list_basins_overlapping_nepal's deliberately generous filter):
this file *is* Nepal's own admin boundary, so every row it contains
already belongs to Nepal.
"""

from __future__ import annotations

import logging

import geopandas as gpd

from . import config
from .aoi import AOI
from .basins import to_utm_geom
from .errors import DataSourceUnavailableError, DistrictNotFoundError

logger = logging.getLogger(__name__)

# Required columns per the HDX COD-AB admin-2 layer's own schema
# (verified against the real downloaded file during implementation —
# see backend/app/data/config.py's LOCAL_ADMIN_DISTRICTS_PATH comment).
PCODE_COLUMN = "adm2_pcode"
NAME_COLUMN = "adm2_name"
PROVINCE_NAME_COLUMN = "adm1_name"

_districts_gdf: gpd.GeoDataFrame | None = None


def _validate_districts_schema(gdf: gpd.GeoDataFrame, path) -> None:
    missing = [c for c in (PCODE_COLUMN, NAME_COLUMN, PROVINCE_NAME_COLUMN) if c not in gdf.columns]
    if missing:
        raise DataSourceUnavailableError(
            f"districts: {path} is missing column(s) {missing}; is this really the HDX COD-AB "
            "admin-level-2 layer? See app/data/districts.py's module docstring."
        )
    geom_types = set(gdf.geom_type.unique())
    if not geom_types <= {"Polygon", "MultiPolygon"}:
        raise DataSourceUnavailableError(
            f"districts: {path} contains {sorted(geom_types)} geometry, not Polygon/MultiPolygon."
        )


def _load_districts() -> gpd.GeoDataFrame:
    global _districts_gdf
    if _districts_gdf is not None:
        return _districts_gdf

    path = config.LOCAL_ADMIN_DISTRICTS_PATH
    if not path.exists():
        raise DataSourceUnavailableError(
            f"districts: no admin-boundaries file at {path}. Download the 'Nepal - Subnational "
            "Administrative Boundaries' (COD-AB) shapefile from "
            "https://data.humdata.org/dataset/cod-ab-npl and place its admin-2 layer there, or "
            "set ADMIN_DISTRICTS_SHAPEFILE_PATH to point at it."
        )

    logger.info("districts: loading admin-2 (district) polygons from %s", path)
    gdf = gpd.read_file(path)
    _validate_districts_schema(gdf, path)

    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    gdf = gdf.set_index(PCODE_COLUMN, drop=False)

    logger.info("districts: loaded %d districts", len(gdf))
    _districts_gdf = gdf
    return _districts_gdf


def reset_districts_cache() -> None:
    """Test-only: mirrors basins.reset_basins_cache() — drop the
    in-memory cache so a subsequent call to _load_districts() re-reads
    from a (possibly newly-monkeypatched) config.LOCAL_ADMIN_DISTRICTS_PATH.
    """
    global _districts_gdf
    _districts_gdf = None


def district_area_km2(polygon) -> float:
    """`polygon`'s own true area in km², reprojected to EPSG:32645
    (SPEC.md, CRS convention: never compute area directly in degrees) —
    mirrors basins.basin_area_km2, reusing the same reprojection via
    basins.to_utm_geom rather than a second Transformer instance.
    """
    return to_utm_geom(polygon).area / 1_000_000.0


def list_districts() -> gpd.GeoDataFrame:
    """All 77 districts — no bbox screening needed (module docstring)."""
    return _load_districts()


def get_district(pcode: str):
    """A single district row (adm2_pcode + adm2_name + adm1_name +
    geometry, plus whatever other COD-AB attribute columns the source
    file carries). Raises DistrictNotFoundError if pcode isn't in the
    loaded dataset.
    """
    gdf = _load_districts()
    try:
        row = gdf.loc[pcode]
    except KeyError:
        raise DistrictNotFoundError(f"no district with pcode={pcode!r}") from None
    if isinstance(row, gpd.GeoDataFrame):
        row = row.iloc[0]
    return row


def district_to_aoi(pcode: str) -> AOI:
    """The bridge from a selected district to the existing AOI pipeline:
    bbox_4326 is the district polygon's bounding envelope (derived
    automatically), polygon is the true district geometry — exactly
    basins.basin_to_aoi's own shape, so every existing AOI-consuming
    function (DEM/WorldCover fetch, the overlay engine, hydrology's
    basin-vs-bbox true-shape clipping) treats a district selection
    identically to a basin selection, with no district-specific code
    needed anywhere downstream of this function.
    """
    district = get_district(pcode)
    polygon = district.geometry
    minx, miny, maxx, maxy = polygon.bounds
    return AOI(bbox_4326=(minx, miny, maxx, maxy), polygon=polygon)
