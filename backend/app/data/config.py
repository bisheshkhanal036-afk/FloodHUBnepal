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

# app/data/validation_extent.py: real, satellite-observed flood extent
# polygons -- for validating the computed risk surface against actual
# ground truth (a *different* thing from every criterion source above,
# all of which feed the risk surface itself; this data never does).
# Local-only, no cloud fallback, same reasoning as basins.py/meteor_flood.py:
# no live windowed-read endpoint exists for any of these -- each is a
# one-time downloaded product. VALIDATION_EVENTS maps a stable event key
# (used in API requests) to the shapefile local_source.
# find_local_raster_covering_aoi-style local dir it lives in -- adding a
# future event (e.g. a genuine Kathmandu-Valley-covering product, or the
# 2017/2019 events once a source is found for them, see SPEC.md) needs
# only one new dict entry here, no code change.
#
# nepal_2024_terai: UN Satellite Centre (UNOSAT) Sentinel-1 SAR flood
# extent, 27 September 2024, Koshi & Madhesh Provinces -- one date from a
# 3-date rapid-mapping product covering the September 2024 Nepal floods
# (244 deaths nationally). Downloaded from HDX
# (data.humdata.org/dataset/flood-impact-assessment-of-the-capital-city-
# of-kathmandu-bagmati-province-nepal-as-of-30-s), licensed CC BY-SA
# (Creative Commons Attribution-ShareAlike -- confirmed directly on that
# HDX dataset's own metadata, not assumed). Despite that dataset's own
# title, this specific file's geometry does NOT reach Kathmandu Valley
# (~85.2-85.5E) -- verified directly by checking its bounds (max
# longitude 87.47E, i.e. comfortably east of Kathmandu, all in the Terai
# lowlands) -- so it validates against real Terai flooding, not this
# project's Kathmandu Valley study area. Flagged explicitly wherever this
# event is surfaced, not silently implied to be local ground truth.
LOCAL_VALIDATION_EXTENTS_DIR = DATA_DIR / "raw" / "validation_extents"
VALIDATION_EVENTS = {
    "nepal_2024_terai": {
        "label": "Nepal floods, 27 Sep 2024 (Koshi & Madhesh Provinces, Terai)",
        "path": "nepal_2024_terai/S1_20240927_FloodExtent_Koshi_Madhesh.shp",
        "attribution": (
            "United Nations Satellite Centre (UNOSAT). Satellite detected water extent, "
            "Koshi and Madhesh Provinces, Nepal, as of 27 September 2024 (Sentinel-1 SAR, "
            "acquired 27 Sep 2024 00:11 UTC). Licensed CC BY-SA. "
            "https://data.humdata.org/dataset/flood-impact-assessment-of-the-capital-city-of-"
            "kathmandu-bagmati-province-nepal-as-of-30-s"
        ),
    },
    # nepal_bipad_flood_points: a POINT inventory, not a filled extent
    # polygon like nepal_2024_terai above -- 2,999 individual, verified
    # flood-occurrence reports nationwide (2011-06-05 to 2026-08-24),
    # from Nepal's BIPAD Portal (bipadportal.gov.np), the national
    # Disaster Information Management System owned by NDRRMA under the
    # Ministry of Home Affairs. Retrieved directly from its own public,
    # unauthenticated REST API (GET /api/v1/incident/?hazard=11 --
    # hazard id 11 = "Flood", confirmed against /api/v1/hazard/'s own
    # listing), no scraping. get_observed_flood_mask/
    # get_validation_extent_geojson (validation_extent.py) needed no
    # code changes for this -- rasterio's rasterize() and geopandas'
    # own I/O are already geometry-type-agnostic, confirmed live against
    # this exact file before registering it here.
    #
    # This is the source that actually closes the "no Kathmandu Valley
    # coverage" gap nepal_2024_terai's own comment above documents: 139
    # of these 2,999 points fall within Kathmandu Valley specifically
    # (54 distinct locations, some flooded repeatedly across different
    # years) -- checked directly, not assumed from the source's national
    # scope. This is also the methodologically standard input for a
    # success-rate/AUC-ROC susceptibility-map validation (Chung & Fabbri
    # method, already cited elsewhere in this project) -- occurrence
    # LOCATIONS, not a filled extent -- which is why
    # observed_flooded_fraction against this event will always be a tiny
    # number (a handful of point-pixels, never a meaningful "% of area"),
    # by design, not a bug.
    #
    # License not formally verified -- no terms-of-use/license page was
    # found on the portal, unlike nepal_2024_terai's confirmed CC BY-SA
    # above; used here as a public, unauthenticated government DRR
    # data-dissemination portal with full attribution. See
    # D:\New folder\README.md's own 2011-2026_Nepal_BIPAD_flood_incidents
    # section for the complete provenance writeup and this exact caveat.
    "nepal_bipad_flood_points": {
        "label": "Nepal flood incidents, 2011-2026 (BIPAD Portal, point inventory)",
        "path": "nepal_bipad_flood_points/points.geojson",
        "attribution": (
            "Nepal BIPAD Portal (Building Information Platform Against Disaster), National "
            "Disaster Risk Reduction and Management Authority (NDRRMA), Ministry of Home "
            "Affairs, Government of Nepal, technical implementation by Youth Innovation Lab. "
            "Flood incident records, 2011-06-05 to 2026-08-24, retrieved via the portal's own "
            "public API (bipadportal.gov.np/api/v1/incident/?hazard=11). "
            "https://bipadportal.gov.np/"
        ),
    },
    # nepal_2024_west_eosrs: EOS Data Analytics (EOS-RS) Sentinel-1 Flood
    # Proxy Map, acquired 12 July 2024, v0.5 -- covers the July 2024
    # monsoon flooding in far-western/Karnali Nepal, NOT the Terai
    # (bounds verified directly: 79.45-82.59E, 27.60-30.94N -- Karnali/
    # Sudurpaschim Province, west of every other registered event's
    # coverage). Single flooded class (`DN`==100 for all 310,573
    # polygons, confirmed by value-count before registering). License
    # not formally verified in the delivered shapefile (no accompanying
    # metadata/license file) -- used here as a named research-provider
    # product with full attribution, same caveat class as
    # nepal_bipad_flood_points above.
    "nepal_2024_west_eosrs": {
        "label": "Nepal floods, 12 Jul 2024 (Karnali/Sudurpaschim, EOS-RS Flood Proxy Map)",
        "path": "EOS-RS_20240712_FPM_S1_Nepal_Floods_v0.5_shp/EOS-RS_20240712_FPM_S1_Nepal_Floods_v0.5_shp.shp",
        "attribution": (
            "EOS Data Analytics (EOS-RS). Sentinel-1 SAR Flood Proxy Map, Nepal, "
            "acquired 12 July 2024, v0.5."
        ),
    },
    # nepal_2024_west_mbrsc: Mohammed Bin Rashid Space Centre (MBRSC,
    # UAE) flood map, derived from imagery dated 7-8 July 2024 (per the
    # shapefile's own ArcGIS lineage metadata and folder/file naming) --
    # the same July 2024 western-Nepal flood event nepal_2024_west_eosrs
    # covers, from an independent provider/methodology (ArcGIS raster
    # classification -> polygon, not EOS-RS's own Sentinel-1 proxy
    # method), over a materially smaller extent (bounds 80.03-80.58E,
    # 28.54-29.00N, entirely inside EOS-RS's own wider coverage --
    # verified directly, not assumed). Kept as a separate event rather
    # than merged with EOS-RS specifically so the two independent
    # detections can be checked against each other, not silently
    # blended into one. Native CRS UTM Zone 44N (EPSG:32644); no
    # accompanying license/citation text found in the delivered
    # metadata, same "not formally verified" caveat as
    # nepal_2024_west_eosrs above.
    "nepal_2024_west_mbrsc": {
        "label": "Nepal floods, 8 Jul 2024 (Karnali, MBRSC flood map)",
        "path": "MBRSC_NEPAL_FLOOD_08TH_JULY_SHP/NEPAL_FLOOD_08TH_JULY.shp",
        "attribution": (
            "Mohammed Bin Rashid Space Centre (MBRSC). Nepal flood extent map, "
            "imagery dated 7-8 July 2024."
        ),
    },
    # rasuwa_2026: this project's own hand-digitized flood extent for the
    # 26 August 2026 Rasuwa/Bhote Koshi-Trishuli-Narayani corridor flood
    # (the same event described in this repo's own SPEC.md project
    # history) -- 10 polygons, ~19.15 km^2 total (summed from the
    # shapefile's own geodesic `area` field, square kilometers),
    # digitized in ArcGIS Pro directly against post-event imagery, not a
    # third-party satellite product like every other event above. Native
    # CRS UTM Zone 45N (EPSG:32645). Since this is the project's own
    # field mapping rather than an external agency's release, its
    # "attribution" names the project instead of an outside source.
    "rasuwa_2026": {
        "label": "Nepal floods, 26 Aug 2026 (Rasuwa/Bhote Koshi-Trishuli-Narayani corridor)",
        "path": "Rasuwa 2026/Rasuwa-2026.shp",
        "attribution": (
            "FloodHUB project team. Hand-digitized post-event flood extent, Rasuwa/Bhote "
            "Koshi-Trishuli-Narayani corridor flood of 26 August 2026, digitized against "
            "post-event imagery."
        ),
    },
    # nepal_2026_emsr927: Copernicus Emergency Management Service
    # (Copernicus EMS) Rapid Mapping activation EMSR927, Grading
    # Analysis (GRA) product, "observedEventA" layer -- created
    # 2026-08-27, one day after the 26 August 2026 flood already covered
    # by rasuwa_2026 above. Delivered as 3 separate AOI products (AOI01
    # 85.324-85.348E/28.150-28.188N, AOI02
    # 85.357-85.380E/28.242-28.280N -- both just north of rasuwa_2026's
    # own corridor; AOI03 85.099-85.193E/27.857-28.009N -- west of the
    # other two, closer to the Trishuli/Nuwakot-Dhading corridor --
    # bounds verified directly from each shapefile, not assumed), but
    # registered here as ONE event with `path` a LIST of all 3
    # shapefiles rather than 3 separate event keys, at explicit request
    # -- one activation, one toggle in the UI, not 3 near-identical
    # entries a user has to select between one at a time.
    # get_observed_flood_mask/get_validation_extent_geojson
    # (validation_extent.py) both read every path in the list and merge
    # them into one GeoDataFrame before rasterizing/serving, reprojecting
    # each independently first (never assuming they share one native CRS
    # -- they don't have to, this project's other multi-source events
    # like nepal_2024_west_mbrsc vs. rasuwa_2026 already differ:
    # EPSG:32644 vs EPSG:32645). AOI01/AOI02 are each a single polygon
    # (~111.08 km^2 / ~125.88 km^2 from each shapefile's own `area`
    # field); AOI03 is 2 polygons (~559.83 km^2 + ~29.25 km^2 =
    # ~589.08 km^2). Combined total ~826 km^2 across all 3 AOIs' 4
    # polygons.
    #
    # Registered here as flood-extent validation data, NOT as a separate
    # landslide/mass-movement hazard event, despite the product's own
    # schema tagging `event_type`/`obj_desc` as "6-Mass Movement"/
    # "Landslide" for all three AOIs (checked directly against each real
    # attribute table before registering, not assumed from the folder
    # name) -- confirmed this is the correct read for this event: the
    # 26 August 2026 disaster was a landslide-triggered flood/debris
    # flow, so the mapped extent is real flood/debris-flow inundation on
    # the ground, even though Copernicus EMS's own event-type
    # vocabulary classifies the *trigger* mechanism (mass movement)
    # rather than the *water* impact this project's validation feature
    # actually checks against. Flagged here explicitly rather than
    # silently registered under a generic label, the same
    # "document, don't hide" pattern this file already uses for every
    # other caveated event above.
    #
    # License not formally verified against a specific open license the
    # way nepal_2024_terai's CC BY-SA is -- the product's own metadata
    # only points to Copernicus EMS's general copyright-notice page
    # (http://emergency.copernicus.eu/mapping/ems/cite-copernicus-ems-
    # mapping-portal); used here as a named EU agency's public rapid-
    # mapping product with full attribution, same caveat class as
    # nepal_2024_west_eosrs/nepal_2024_west_mbrsc above.
    "nepal_2026_emsr927": {
        "label": "Nepal floods, 26 Aug 2026 (Copernicus EMSR927, landslide-triggered debris flow, AOI01-03)",
        "path": [
            "EMSR927_AOI01_GRA_PRODUCT_v1/EMSR927_AOI01_GRA_PRODUCT_observedEventA_v1.shp",
            "EMSR927_AOI02_GRA_PRODUCT_v1/EMSR927_AOI02_GRA_PRODUCT_observedEventA_v1.shp",
            "EMSR927_AOI03_GRA_PRODUCT_v1/EMSR927_AOI03_GRA_PRODUCT_observedEventA_v1.shp",
        ],
        "attribution": (
            "Copernicus Emergency Management Service (© European Union), Rapid Mapping "
            "activation EMSR927, Grading product, AOI01-AOI03 observed event extent, created "
            "27 August 2026. Full copyright notice: "
            "http://emergency.copernicus.eu/mapping/ems/cite-copernicus-ems-mapping-portal"
        ),
    },
}

# Shelter-site identification (app/overlay/shelters.py) -- a candidate
# building's own footprint area (m^2, computed on the UTM grid, never
# raw EPSG:4326 degrees, per SPEC.md's CRS convention) must be at least
# this large to be considered a candidate large/institutional-scale
# structure (a school, community hall, or similar building genuinely
# large enough to shelter people). Not literature-calibrated -- a
# structurally reasonable placeholder (250 m^2 is roughly a small
# school building's footprint) in the same documented-placeholder spirit
# as DRAINAGE_DENSITY_THRESHOLD_CELLS/DRAINAGE_DENSITY_WINDOW_RADIUS_M
# above, pending real calibration against a known set of Kathmandu
# Valley shelter buildings. Overridable per-request
# (ShelterIdentificationRequest.min_footprint_area_m2), this is only the
# default.
SHELTER_MIN_FOOTPRINT_AREA_M2 = float(os.environ.get("SHELTER_MIN_FOOTPRINT_AREA_M2", "250.0"))

# Default number of ranked candidates POST /api/overlay/shelters returns
# when the caller doesn't specify top_n.
SHELTER_DEFAULT_TOP_N = int(os.environ.get("SHELTER_DEFAULT_TOP_N", "20"))
