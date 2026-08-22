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
