"""Attribution strings that must accompany every API response serving
data derived from each source, regardless of which path (local file,
cloud/S3, or R2) actually served it.
"""

from __future__ import annotations

# Verified against Copernicus Data Space Ecosystem's published DEM license
# (License-COPDEM-30.pdf) during implementation of this module.
DEM_ATTRIBUTION = (
    "Copernicus GLO-30 DEM: © DLR e.V. 2010-2014 and © Airbus Defence and "
    "Space GmbH 2014-2018 provided under COPERNICUS by the European Union "
    "and ESA; all rights reserved."
)

# The recommended citation published with the dataset (Zanaga et al., 2022,
# https://doi.org/10.5281/zenodo.7254221), verified during implementation.
WORLDCOVER_ATTRIBUTION = (
    "Zanaga, D., Van De Kerchove, R., Daems, D., De Keersmaecker, W., "
    "Brockmann, C., Kirches, G., Wevers, J., Cartus, O., Santoro, M., "
    "Fritz, S., Lesiv, M., Herold, M., Tsendbazar, N.E., Xu, P., Ramoino, "
    "F., Arino, O. (2022). ESA WorldCover 10 m 2021 v200. "
    "https://doi.org/10.5281/zenodo.7254221"
)

OSM_ATTRIBUTION = "© OpenStreetMap contributors"

# NDVI is derived on the fly from Sentinel-2 L2A surface-reflectance bands
# (B08 NIR, B04 red), read from the public sentinel-cogs bucket indexed by
# Element 84's Earth Search STAC. Copernicus Sentinel data carries a
# standard attribution requirement for derived products.
NDVI_ATTRIBUTION = (
    "Contains modified Copernicus Sentinel-2 L2A data, processed by ESA; "
    "accessed via Element 84 Earth Search (AWS Open Data). NDVI computed "
    "from the near-infrared (B08) and red (B04) bands."
)

# The citation text published on the dataset's AWS Open Data Registry
# listing (https://registry.opendata.aws/dataforgood-fb-hrsl/), verified
# during implementation of population.py. That listing's suggested
# format wraps this in "...was accessed on [DATE] from
# https://registry.opendata.aws/dataforgood-fb-hrsl. ... Accessed [DAY
# MONTH YEAR]." -- a citation-generation instruction for someone citing
# this in a document with a fixed access date, not a literal string to
# embed here; every other ATTRIBUTION constant in this file is a static,
# undated citation, so the "accessed on" wrapper is deliberately dropped
# to match that convention. Flagged as a decision to confirm.
POPULATION_ATTRIBUTION = (
    "Meta and Center for International Earth Science Information Network - CIESIN - Columbia University. "
    "2022. High Resolution Settlement Layer (HRSL). Source imagery for HRSL © 2016 Maxar."
)

# ISRIC's own recommended citation for SoilGrids 2.0 (Poggio et al., 2021),
# verified during implementation of soil.py. Data licensed CC BY 4.0.
SOIL_ATTRIBUTION = (
    "Poggio, L., de Sousa, L. M., Batjes, N. H., Heuvelink, G. B. M., Kempen, B., Ribeiro, E., and "
    "Rossiter, D. (2021). SoilGrids 2.0: producing soil information for the globe with quantified "
    "spatial uncertainty. SOIL, 7, 217-240. https://doi.org/10.5194/soil-7-217-2021. "
    "© ISRIC — World Soil Information, licensed under CC BY 4.0."
)

# Nepal's national rain-gauge network, operated by the Department of
# Hydrology and Meteorology (DHM). The ETCCDI climatological indices
# interpolated by rainfall.py were computed from the 1980-2022 daily
# record over 254 quality-controlled gauges. DHM data is provided for
# research use; the derived station-climatology table committed at
# app/data/resources/nepal_precip_stations.csv contains aggregated
# indices, not the raw daily series.
DHM_PRECIP_ATTRIBUTION = (
    "Precipitation: Department of Hydrology and Meteorology (DHM), Government of Nepal — "
    "daily rain-gauge record 1980-2022, 254 stations. ETCCDI climatological indices "
    "(Rx1day, Rx5day, PRCPTOT, R95pTOT) derived from that record and interpolated to the "
    "analysis grid by inverse distance weighting."
)


# Methodology references, as distinct from the data-source attributions
# above: these credit the *method* this project implements, not a
# dataset it reads. Kept here so there is exactly one place in the
# backend holding full bibliographic details, rather than the informal
# "the Siraha paper" shorthand that used to appear in hydrology.py with
# the complete citation living only inside a test docstring
# (tests/test_ahp_core.py, which transcribes this paper's Tables 4-5).
#
# Parajuli et al. (2023) is open access under CC BY 4.0, so its tables
# and figures may be reused with attribution.
METHODOLOGY_CITATIONS = {
    "ahp": (
        "Saaty, T. L. (1980). The Analytic Hierarchy Process: Planning, Priority Setting, "
        "Resource Allocation. McGraw-Hill, New York."
    ),
    "reference_method": (
        "Parajuli, G., Neupane, S., Kunwar, S., Adhikari, R., & Acharya, T. D. (2023). "
        "A GIS-Based Evacuation Route Planning in Flood-Susceptible Area of Siraha "
        "Municipality, Nepal. ISPRS International Journal of Geo-Information, 12(7), 286. "
        "https://doi.org/10.3390/ijgi12070286"
    ),
}
