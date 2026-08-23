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
