"""Environment-driven configuration for the geospatial data layer.

Every path/URL here can be overridden via environment variable so the
same code runs unmodified in local dev (files under DATA_DIR) and in a
deployed environment that may have zero local files (env vars pointing
at the R2 fallback only).
"""

from __future__ import annotations

import os
from pathlib import Path

# Root of all local geospatial data: raw pre-downloaded sources (optional
# fast-path only) and the processed/clipped-per-AOI cache (never a raw
# source itself). Defaults to backend/data/, i.e. a sibling of app/.
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))

LOCAL_DEM_DIR = DATA_DIR / "raw" / "dem"
LOCAL_WORLDCOVER_DIR = DATA_DIR / "raw" / "worldcover"
LOCAL_POPULATION_DIR = DATA_DIR / "raw" / "population"
LOCAL_NDVI_DIR = DATA_DIR / "raw" / "ndvi"
LOCAL_SOIL_DIR = DATA_DIR / "raw" / "soil"
LOCAL_CHIRPS_DIR = DATA_DIR / "raw" / "chirps"
LOCAL_METEOR_FLOOD_DIR = DATA_DIR / "raw" / "meteor_flood"

# chirps.py's cloud fallback: UC Santa Barbara Climate Hazards Center's own
# public, unauthenticated hosting (data.chc.ucsb.edu) -- verified live
# during implementation to need no authentication, same as SoilGrids and
# unlike GPM IMERG (whose AWS bucket is gesdisc-cumulus-prod-*protected*,
# requiring Earthdata Login credentials -- rejected for the same reason
# HYSOGs250m was). This one file is CHIRPS-2.0's own 44-year (1981-2024)
# mean-annual-precipitation climatology -- a single global raster, not a
# per-date fetch, since a flood-risk criterion wants "how much does it
# normally rain here", not one day's weather. Verified live: real ~57.6MB
# GeoTIFF, CRS EPSG:4326 (no Homolosine-style reprojection-before-
# windowing needed, unlike soil.py's SoilGrids source), dtype float32,
# native resolution 0.05° (~5.5km), nodata -9999.0 (confirmed by sampling
# an open-ocean window; the file's own GDAL metadata does not declare a
# NoData tag, so this value is supplied explicitly here rather than read
# off the dataset the way dem.py/worldcover.py do for sources that do
# declare one). Covers 50°S-50°N, comfortably including Nepal (26.3-
# 30.5°N, basins.py's own NEPAL_BBOX_4326) -- CHIRPS's coverage note is
# sometimes misread as excluding Nepal; it does not.
CHIRPS_NODATA = -9999.0
CHIRPS_ANNUAL_NORMALS_URL = os.environ.get(
    "CHIRPS_ANNUAL_NORMALS_URL",
    "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_annual/tifs/chirps-v2.0.1981-2024.44yrs.tif",
)

# soil.py's cloud fallback: ISRIC SoilGrids 2.0's own public, unauthenticated
# hosting (files.isric.org) -- unlike HYSOGs250m (NASA/ORNL DAAC), whose
# real granule URLs (found via the CMR API, not its catalog page) turned
# out to sit under /protected/ and require Earthdata Login, SoilGrids was
# verified live during implementation to need no authentication at all: a
# plain rasterio.open("/vsicurl/https://files.isric.org/...") against this
# exact VRT succeeded with no credentials. One VRT per property per depth
# interval; only the shallowest interval (0-5cm, topsoil) is used here,
# matching this criterion's own "surface infiltration capacity" framing.
# Live-verified via a real windowed read over Kathmandu Valley during
# implementation: CRS is Interrupted Goode Homolosine (a global, non-EPSG:
# 4326/non-UTM projection -- soil.py reprojects the AOI bbox into it
# explicitly rather than assuming src CRS == EPSG:4326 the way dem.py/
# worldcover.py/population.py do), dtype int16, nodata=-32768, native
# resolution 250m.
SOILGRIDS_SAND_VRT_URL = os.environ.get(
    "SOILGRIDS_SAND_VRT_URL", "https://files.isric.org/soilgrids/latest/data/sand/sand_0-5cm_mean.vrt"
)

# meteor_flood.py: METEOR Project's Nepal flood hazard maps (Fluvial
# Defended/Undefended, Pluvial x 10 return periods each), produced with
# the Fathom global flood hazard modelling framework -- see
# attribution.py's METEOR_FLOOD_ATTRIBUTION for the full citation/license
# writeup. Verified directly against the flood map's own page HTML
# during implementation (bypassing a summarizer, at explicit request, to
# be completely sure): licensed ODbL (Open Data Commons Open Database
# License) -- NOT the CC BY-NC-SA 4.0 that covers METEOR's separate,
# differently-licensed Exposure Data (building-count) product, an easy
# conflation this project's own research first fell into and then
# corrected against the raw page source. ODbL is the same license
# OpenStreetMap itself uses (see OSM_ATTRIBUTION) -- commercial use and
# redistribution both permitted, with attribution.
#
# Local-only, unlike DEM/WorldCover/SoilGrids/CHIRPS above: no live
# windowed-read endpoint exists for METEOR's raw numeric water-depth
# values -- METEOR's own map only serves pre-styled WMS/WMTS tiles (RGB
# PNG, verified live during implementation by fetching a real tile and
# confirming genuine flood-extent geometry over Kathmandu), which are
# fine for a reference overlay but useless as numeric criterion input.
# The only way to get real depth values is METEOR's own downloadable
# QGIS project package
# (https://maps.meteor-project.org/map/flood-npl/download, 30 GeoTIFFs,
# ~335MB zipped, confirmed live during implementation) -- a deployment
# that wants this criterion must download it and place the wanted
# layer(s) here, named exactly as the zip's own layers/{TYPE}_{RETURN}.tif
# convention (e.g. "FD_1in100.tif"). meteor_flood.py raises
# DataSourceUnavailableError rather than silently degrading if the
# configured file isn't present -- there is no cloud fallback to fall
# back to.
#
# TYPE is one of FD (Fluvial Defended), FU (Fluvial Undefended), P
# (Pluvial); RETURN is one of 5/10/20/50/75/100/200/250/500/1000
# ("1inN"-year return period), per METEOR's own WMS layer catalog
# (verified live via GetCapabilities during implementation). Defaults to
# FD/1in100: "defended" reflects expected flooding given Nepal's actual
# flood-defence infrastructure (more realistic for present-day risk than
# "undefended"), and 1-in-100 is the standard regulatory/planning
# benchmark return period widely used in flood risk assessment.
#
# Verified live against the real downloaded FD_1in100.tif during
# implementation: CRS EPSG:4326, dtype float32, 10000x6000px covering
# all of Nepal (80.01-88.34E, 25.48-30.48N), native resolution
# 0.0008333... deg (~90m, "3 arcsecond" per METEOR's own metadata.txt),
# values are modeled water depth in meters (metadata.txt: "Depths are
# shown in meters... the maximum water depth that would be expected if a
# flood event of the specified return period were occurring"). Two raw
# sentinel values found by direct inspection of the real pixel data
# (neither declared as a GDAL NoData tag -- ds.nodata reads None):
# -9999.0 (97.2% of pixels -- outside the Fathom model's simulated
# floodplain domain entirely, e.g. hillslope/ridge terrain the model
# never attempts to flood) and 999.0 (0.018% of pixels -- a much rarer
# masked value, plausibly a permanent-water/model-boundary flag). The
# remaining ~2.8% of pixels are real modeled depths, range 0.0-5.0m in
# this file.
#
# meteor_flood.py does NOT treat either sentinel as nodata (a first
# version did; changed after a real user-reported bug -- "only the
# meteor area gets flood hazard output", since ~97% of any AOI being
# excluded left almost nothing classified). -9999 is instead resolved to
# a real depth of 0.0m: metadata.txt's own documented semantics mean
# those pixels are ones the model deliberately never attempts to flood,
# which for a flood-hazard criterion genuinely does mean "no hazard
# here", not "unknown" -- see meteor_flood.py's own module docstring for
# the full reasoning, including why 999 is deliberately NOT given the
# same treatment (it means permanent water, i.e. high risk, not the
# absence of it).
METEOR_FLOOD_TYPE = os.environ.get("METEOR_FLOOD_TYPE", "FD")
METEOR_FLOOD_RETURN_PERIOD = os.environ.get("METEOR_FLOOD_RETURN_PERIOD", "1in100")
METEOR_FLOOD_RAW_SENTINELS = (-9999.0, 999.0)  # (outside_domain, permanent_water) -- order matters, see meteor_flood.py's _resolve_sentinels

# NDVI (ndvi.py) is computed on the fly from Sentinel-2 L2A red/NIR bands,
# discovered through Element 84's public Earth Search STAC API and read
# from the public sentinel-cogs bucket — no auth, same "live cloud read"
# pattern as dem.py/worldcover.py, and it obeys GDAL_HTTP_RETRY_ENV below
# for the actual COG reads. All overridable so the STAC endpoint,
# collection, or scene-selection window can change without a code edit.
NDVI_STAC_SEARCH_URL = os.environ.get(
    "NDVI_STAC_SEARCH_URL", "https://earth-search.aws.element84.com/v1/search"
)
NDVI_STAC_COLLECTION = os.environ.get("NDVI_STAC_COLLECTION", "sentinel-2-l2a")
# Max scene cloud cover (%) to accept; the least-cloudy scene under this is
# used. Relaxed automatically if nothing qualifies (see ndvi.py).
NDVI_MAX_CLOUD_COVER = float(os.environ.get("NDVI_MAX_CLOUD_COVER", "20"))
# Optional ISO date range "start/end" to restrict scene search (e.g. a dry
# season). Empty = no date restriction (search all available scenes).
NDVI_DATE_RANGE = os.environ.get("NDVI_DATE_RANGE", "")

# A directory, not a fixed filename — mirrors LOCAL_DEM_DIR/LOCAL_
# WORLDCOVER_DIR's own local_source.find_local_raster_covering_aoi
# pattern (glob a directory rather than require an exact name) rather
# than the single hardcoded "nepal-latest.osm.pbf" this used to be.
# That exact-name requirement was a real bug: a Geofabrik/Planet OSM
# export's filename always carries its own extract date (e.g.
# "nepal-260821.osm.pbf"), so a real downloaded file placed here would
# never match and osm.py would silently fall through to the (usually
# unconfigured) R2 fallback instead of ever using it — caught by
# verifying against a real 412MB Nepal extract during implementation.
# osm.py's _find_local_pbf() picks the most-recently-modified
# "*.osm.pbf" file in this directory.
LOCAL_OSM_DIR = Path(os.environ.get("OSM_PBF_DIR", str(DATA_DIR / "raw" / "osm")))

# Pre-processed Nepal-wide extracts (buildings/roads/waterways, geometry
# only, FlatGeobuf) -- osm.py's FASTEST local path, checked before the
# raw *.osm.pbf. Fixed filenames (not a glob like LOCAL_OSM_DIR above):
# unlike a downloaded Geofabrik/Planet .pbf, these are generated BY this
# project (see backend/data/raw/osm/processed/README.md for how), so
# there's no external naming convention to accommodate.
#
# Why this exists / why it's faster than parsing the .pbf: verified live
# against this project's real 412MB Nepal .pbf and the Geofabrik
# shapefile export it was generated from -- pyrosm parsing the raw .pbf
# for a single AOI took ~145-210s (no partial/indexed read of a raw .pbf
# is possible; pyrosm has to scan+decode the whole file every time).
# FlatGeobuf's built-in packed R-tree index turns that into a genuine
# bbox-filtered partial read: 0.015s-4.4s for the same kind of AOI
# (buildings, being ~8.26M features nationwide, is the slowest of the
# three, but still 20-100x faster than the .pbf path). Kept as a
# *separate* fast path rather than folded into _find_local_pbf/
# _parse_local_pbf, since it's a different file format needing a
# different reader (geopandas' bbox= read, not pyrosm) -- the .pbf path
# stays as the fallback for a local file dropped in without regenerating
# these extracts, and R2 stays the fallback for a deployment with no
# local files of either kind.
LOCAL_OSM_PROCESSED_DIR = Path(os.environ.get("OSM_PROCESSED_DIR", str(LOCAL_OSM_DIR / "processed")))

# HydroBASINS Asia (region "as"), "Standard" (polygon) product — NOT the
# "Pour Points" product, which is point geometry and can't represent a
# basin boundary. Download from
# https://www.hydrosheds.org/products/hydrobasins. Two resolutions are
# supported side by side (app/data/basins.py's SUPPORTED_BASIN_LEVELS):
# level 8 (~28,907 basins Asia-wide, coarser/larger catchments — the
# original, still-default level) and level 9 (~77,849 basins, finer
# sub-catchments — added so a user can pick whichever granularity suits
# their AOI, e.g. a small urban catchment vs. a whole valley). HYBAS_ID
# encodes region+level in its own digits (verified empirically: every
# level-8 ID in this dataset starts "408…", every level-9 ID "409…"), so
# the two levels' IDs never collide and can be looked up by ID alone once
# the caller states which level's file to search.
# Overridable since the actual downloaded filename may differ from
# HydroSHEDS' own naming convention depending on how/when it was
# obtained. Default paths verified against the actual placed downloads
# during implementation: HydroSHEDS' own zip layout nests each
# shapefile in a same-named subdirectory.
LOCAL_BASINS_PATH = Path(
    os.environ.get(
        "BASINS_SHAPEFILE_PATH",
        str(DATA_DIR / "raw" / "basins" / "hybas_as_lev08_v1c" / "hybas_as_lev08_v1c.shp"),
    )
)
LOCAL_BASINS_LEV09_PATH = Path(
    os.environ.get(
        "BASINS_LEV09_SHAPEFILE_PATH",
        str(DATA_DIR / "raw" / "basins" / "hybas_as_lev09_v1c" / "hybas_as_lev09_v1c.shp"),
    )
)

# Nepal's true country boundary (ADM0) plus its administrative
# subdivisions, used both (a) to compute an accurate support-status
# area-percentage for basins.classify_support_status (optional: if
# LOCAL_NEPAL_BOUNDARY_PATH is absent, that classification falls back to
# the rough NEPAL_BBOX_4326 rectangle proxy in basins.py rather than
# failing) and (b) as the source for district-based AOI selection
# (app/data/districts.py). Source: OCHA/HDX's "Nepal - Subnational
# Administrative Boundaries" COD-AB dataset
# (https://data.humdata.org/dataset/cod-ab-npl), produced by Nepal's own
# Survey Department + UN Resident Coordinator's Office, quality-assured
# by ITOS/USAID — licensed CC BY-IGO (attribution required; unlike the
# HERMES source used earlier in this project, or GADM, both of which
# permit non-commercial use only, this one permits commercial use and
# redistribution too). The one file covers admin levels 0 (country) —
# 3 (local level); this project uses level 0 for the Nepal boundary and
# level 2 (77 districts) for district-based AOI selection.
LOCAL_NEPAL_BOUNDARY_PATH = Path(
    os.environ.get(
        "NEPAL_BOUNDARY_SHAPEFILE_PATH",
        str(DATA_DIR / "raw" / "basins" / "npl_admin_boundaries.shp" / "npl_admin0.shp"),
    )
)
LOCAL_ADMIN_DISTRICTS_PATH = Path(
    os.environ.get(
        "ADMIN_DISTRICTS_SHAPEFILE_PATH",
        str(DATA_DIR / "raw" / "basins" / "npl_admin_boundaries.shp" / "npl_admin2.shp"),
    )
)

PROCESSED_CACHE_DIR = DATA_DIR / "cache" / "processed"

# OSM fallback: the same pre-processed Nepal buildings+roads FlatGeobuf
# extracts LOCAL_OSM_PROCESSED_DIR points at locally, instead hosted on a
# configurable S3-compatible bucket (Cloudflare R2 in production) for a
# deployment with no local files. Must be plain public object URLs
# ending in .fgb (format is detected from the URL, same as any local
# path) -- osm.py's _read_remote_fgb does a bbox-filtered *partial* read
# over HTTP (FlatGeobuf's own range-request support), not a whole-file
# download, so this scales the same way the local read does even for the
# ~1.9GB buildings extract. Two separate URLs rather than one bucket
# name, so the extract doesn't have to be a single combined file and the
# naming convention isn't hardcoded here — see the "decisions to
# confirm" note on this choice.
OSM_R2_BUILDINGS_URL = os.environ.get("OSM_R2_BUILDINGS_URL")
OSM_R2_ROADS_URL = os.environ.get("OSM_R2_ROADS_URL")

# Same fallback pattern, for osm.py's get_waterways() (dist_to_river's
# source). A separate URL/file rather than folding waterways into the
# roads or buildings extract, so each pre-processed extract stays a
# single-geometry-type file. Confirmed.
OSM_R2_WATERWAYS_URL = os.environ.get("OSM_R2_WATERWAYS_URL")

# Drainage density (app/data/hydrology.py): the flow-accumulation cell
# count at/above which a pixel is treated as part of the synthetic
# stream network. NOT literature-calibrated here — a structurally
# reasonable placeholder (500 cells @ 10m resolution = 5 hectares of
# upstream contributing area) pending an actual value derived from a
# real Kathmandu Valley stream-network comparison (confirmed as a
# placeholder; the real value is still to be set via literature/
# calibration). Overridable via env var (and folded into hydrology.py's
# cache versioning) so recalibrating it never needs a code change or
# risks serving a stale cached result computed under the old threshold.
DRAINAGE_DENSITY_THRESHOLD_CELLS = int(os.environ.get("DRAINAGE_DENSITY_THRESHOLD_CELLS", "500"))

# Radius, in meters, of the circular moving window hydrology.py uses to
# turn the extracted stream network into a continuous per-pixel
# drainage-density raster (see hydrology.compute_drainage_density_raster).
# Not specified in the brief; 500m chosen as a plausible Kathmandu-
# Valley-scale neighborhood (local enough to stay meaningful at 10m
# resolution, wide enough not to be dominated by single-pixel noise).
# Confirmed, same as the threshold above.
DRAINAGE_DENSITY_WINDOW_RADIUS_M = float(os.environ.get("DRAINAGE_DENSITY_WINDOW_RADIUS_M", "500.0"))

# Radius, in meters, of the circular moving window density_raster.py
# uses to turn OSM building footprints into a continuous per-pixel
# building-density (Exposure cluster) raster. Deliberately smaller than
# DRAINAGE_DENSITY_WINDOW_RADIUS_M above: buildings vary at a finer
# spatial scale than stream networks, so a 500m neighborhood would
# over-smooth block-to-block density differences that matter for
# exposure. 200m chosen as a "roughly one city block" scale; not
# literature-calibrated, overridable, folded into
# get_building_density's cache version.
BUILDING_DENSITY_WINDOW_RADIUS_M = float(os.environ.get("BUILDING_DENSITY_WINDOW_RADIUS_M", "200.0"))

# Live cloud-fallback raster reads (dem.py's Copernicus DEM, worldcover.py's
# ESA WorldCover -- both a bare rasterio.open("https://...") straight
# against a public S3 bucket) hit occasional transient failures:
# "RasterioIOError: CURL error: Empty reply from server", reproduced live
# during a normal browser session. Not a code bug or a dead endpoint --
# a plain urllib range request to the exact same tile URL, run
# immediately after, succeeded in under a second. GDAL's own HTTP layer
# already retries this class of transient failure (and is respected for
# any http(s)-backed dataset open, not only explicit /vsicurl/ paths) far
# more robustly than a hand-rolled Python retry loop would, so both fetch
# functions open their datasets inside `with rasterio.Env(**GDAL_HTTP_RETRY_ENV):`.
GDAL_HTTP_RETRY_ENV = {
    "GDAL_HTTP_MAX_RETRY": int(os.environ.get("GDAL_HTTP_MAX_RETRY", "3")),
    "GDAL_HTTP_RETRY_DELAY": float(os.environ.get("GDAL_HTTP_RETRY_DELAY", "1.0")),
    "GDAL_HTTP_TIMEOUT": int(os.environ.get("GDAL_HTTP_TIMEOUT", "30")),
}

# population.py's S3 bucket (s3://dataforgood-fb-data) is hosted in
# us-east-1, not whatever region GDAL/the AWS SDK would otherwise infer
# by default -- unlike the Copernicus DEM/WorldCover buckets, which this
# project accesses without ever needing to set a region at all. Included
# defensively per the brief's explicit instruction; live testing during
# implementation (a real windowed read over Kathmandu Valley) actually
# succeeded via plain rasterio.open() over this exact bucket/VRT with NO
# region config set at all -- the same plain-HTTPS-via-GDAL's-generic-
# vsicurl-handler access pattern DEM/WorldCover already use, which
# appears to sidestep AWS SDK-style region resolution entirely (that
# only applies to /vsis3/-style access, which none of these three
# sources use). Kept anyway since it's harmless and this is what was
# asked for -- flagged as a "decision to confirm" either way.
POPULATION_S3_REGION_ENV = {
    "AWS_DEFAULT_REGION": os.environ.get("POPULATION_S3_REGION", "us-east-1"),
}
