// Static credits content for the landing page's Credits section and the
// in-tool About modal (Sidebar.jsx). This is deliberately NOT a live API
// call: the landing page is shown before any AOI/compute exists, so
// there is no request in flight yet to read attribution off of.
//
// SOURCE_ATTRIBUTIONS below are copied VERBATIM from
// backend/app/data/attribution.py's own constants -- the same strings
// ResultPanel already renders from a live compute response's
// `result.attribution`. If those backend constants ever change, this
// file needs a matching update to stay in sync (there's no automated
// link between the two, since this file exists precisely so the credits
// page doesn't need a backend round-trip).
//
// Real gap closed here: only DEM/WorldCover/OSM were ever mirrored to
// this file, even after NDVI, population_density, soil_infiltration,
// rainfall, and precipitation_chirps were each added as registered
// criterion sources (backend/app/overlay/sources.py) with their own
// attribution constants (backend/app/data/attribution.py) -- all five
// were missing from the landing page / About modal credits entirely.
export const SOURCE_ATTRIBUTIONS = [
  {
    id: 'dem',
    name: 'Copernicus GLO-30 DEM',
    text: 'Copernicus GLO-30 DEM: © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved.',
  },
  {
    id: 'worldcover',
    name: 'ESA WorldCover',
    text: 'Zanaga, D., Van De Kerchove, R., Daems, D., De Keersmaecker, W., Brockmann, C., Kirches, G., Wevers, J., Cartus, O., Santoro, M., Fritz, S., Lesiv, M., Herold, M., Tsendbazar, N.E., Xu, P., Ramoino, F., Arino, O. (2022). ESA WorldCover 10 m 2021 v200. https://doi.org/10.5281/zenodo.7254221',
  },
  {
    id: 'osm',
    name: 'OpenStreetMap',
    text: '© OpenStreetMap contributors. Buildings, road network, and waterways (rivers/streams/canals) for exposure and hydrological criteria.',
  },
  {
    id: 'ndvi',
    name: 'Sentinel-2 (NDVI)',
    text: 'Contains modified Copernicus Sentinel-2 L2A data, processed by ESA; accessed via Element 84 Earth Search (AWS Open Data). NDVI computed from the near-infrared (B08) and red (B04) bands.',
  },
  {
    id: 'population',
    name: 'Meta/CIESIN HRSL',
    text: 'Meta and Center for International Earth Science Information Network - CIESIN - Columbia University. 2022. High Resolution Settlement Layer (HRSL). Source imagery for HRSL © 2016 Maxar.',
  },
  {
    id: 'soil',
    name: 'ISRIC SoilGrids 2.0',
    text: 'Poggio, L., de Sousa, L. M., Batjes, N. H., Heuvelink, G. B. M., Kempen, B., Ribeiro, E., and Rossiter, D. (2021). SoilGrids 2.0: producing soil information for the globe with quantified spatial uncertainty. SOIL, 7, 217-240. https://doi.org/10.5194/soil-7-217-2021. © ISRIC — World Soil Information, licensed under CC BY 4.0.',
  },
  {
    id: 'chirps',
    name: 'CHIRPS satellite precipitation',
    text: 'Funk, C., Peterson, P., Landsfeld, M., Pedreros, D., Verdin, J., Shukla, S., Husak, G., Rowland, J., Harrison, L., Hoell, A., and Michaelsen, J. (2015). The climate hazards infrared precipitation with stations—a new environmental record for monitoring extremes. Scientific Data, 2, 150066. https://doi.org/10.1038/sdata.2015.66. Climate Hazards Center, UC Santa Barbara — public domain.',
  },
  {
    id: 'chirps-prelim',
    name: 'CHIRPS v3 preliminary daily precipitation',
    text: 'Funk, C. et al. (2015). The climate hazards infrared precipitation with stations — a new environmental record for monitoring extremes. Scientific Data, 2, 150066. https://doi.org/10.1038/sdata.2015.66. CHIRPS v3 preliminary daily data (Climate Hazards Center, UC Santa Barbara + USGS), IMERG-disaggregated. Public domain / CC BY 4.0.',
  },
  {
    id: 'meteor',
    name: 'METEOR Project flood hazard maps',
    text: 'Nepal flood hazard maps: METEOR Project Consortium (published 2019-03-06), produced using the Fathom global flood hazard modelling framework (Sampson et al., 2015, https://doi.org/10.1002/2015WR016954; Smith et al., 2015, https://doi.org/10.1002/2014WR015814) on the MERIT global DEM/hydrography (Yamazaki et al., 2017, https://doi.org/10.1002/2017GL072874; Yamazaki et al., 2019, https://doi.org/10.1029/2019WR024873). Licensed under the Open Data Commons Open Database License (ODbL): https://opendatacommons.org/licenses/odbl/index.html. Source: https://maps.meteor-project.org/map/flood-npl/',
  },
]

// Three additional data sources used by this project (AOI/basin/
// district selection and the Nepal boundary refinement) that don't go
// through overlay compute's per-request attribution list, so they
// aren't in SOURCE_ATTRIBUTIONS above -- credited separately here
// instead. None has a formal attribution constant in the backend the
// way DEM/WorldCover/OSM do (see backend/app/data/attribution.py), so
// these descriptions are written from the source references already in
// backend/app/data/basins.py, districts.py, and config.py's own
// comments, not a verbatim copy of a backend string.
export const ADDITIONAL_SOURCE_CREDITS = [
  {
    id: 'hydrobasins',
    name: 'HydroBASINS (HydroSHEDS)',
    text: 'HydroBASINS Asia, levels 8 and 9 — basin polygons used for basin-based AOI selection, at a coarser or finer resolution respectively. hydrosheds.org/products/hydrobasins',
  },
  {
    id: 'nepal-boundary',
    name: 'Nepal administrative boundaries',
    text: 'OCHA/HDX "Nepal - Subnational Administrative Boundaries" (COD-AB), produced by Nepal’s Survey Department and the UN Resident Coordinator’s Office (data.humdata.org/dataset/cod-ab-npl) — used to refine basin support-status classification near the border, and as the source for district-based AOI selection (77 districts). Licensed CC BY-IGO (attribution required; commercial use and redistribution permitted).',
  },
]

// Methodology citations -- copied VERBATIM from backend/app/data/
// attribution.py's own METHODOLOGY_CITATIONS (the backend's single
// source of truth), same reasoning as SOURCE_ATTRIBUTIONS above. At
// explicit request, these are now shown ONLY here (CreditsSection.jsx,
// rendered by AboutModal -- the in-tool "info" button) and never on the
// landing page itself (LandingPage.jsx's own copy describes the same
// methods without a citation attached to the sentence). The paper is
// open access under CC BY 4.0. Also surfaced per-criterion through
// src/config/literature.js's REFERENCES, which the LiteratureModal
// already renders -- a second, independent "info button" path to the
// exact same reference_method citation, not a duplicate to reconcile.
export const METHODOLOGY_CITATIONS = [
  {
    id: 'ahp',
    name: 'Analytic Hierarchy Process (AHP)',
    text: 'Saaty, T. L. (1980). The Analytic Hierarchy Process: Planning, Priority Setting, Resource Allocation. McGraw-Hill, New York.',
  },
  {
    id: 'reference_method',
    name: 'Reference method',
    text: 'Parajuli, G., Neupane, S., Kunwar, S., Adhikari, R., & Acharya, T. D. (2023). A GIS-Based Evacuation Route Planning in Flood-Susceptible Area of Siraha Municipality, Nepal. ISPRS International Journal of Geo-Information, 12(7), 286. https://doi.org/10.3390/ijgi12070286',
  },
]

// Team credits: the 3 people who built this project. `photo` is an
// imported image, cropped to a head-and-shoulders square from the
// original photo each person sent (originals were full-body shots --
// cropped with Pillow so the circular avatar frame doesn't shrink the
// face to a speck). CreditsSection falls back to a plain initial-letter
// avatar for anyone without a `photo` set, so this list still works if
// a photo is ever removed.
//
// Photo-to-name assignment confirmed by the user (the initial send-order
// guess had it wrong -- the actual files under frontend/src/assets/team/
// were renamed to match, so these imports need no further mapping).
import bisheshPhoto from '../assets/team/team-bishesh.jpg'
import aayushPhoto from '../assets/team/team-aayush.jpg'
import anujPhoto from '../assets/team/team-anuj.jpg'

// Order matters here (both the landing page's own 3-across team-showcase
// grid and CreditsSection's own grid render in this exact order) --
// Bishesh Khanal specifically in the middle position, at explicit
// request, not first.
export const TEAM_CREDITS = [
  {
    id: 2,
    name: 'Aayush Roka',
    email: 'er.rokaayush77@gmail.com',
    linkedin: 'https://www.linkedin.com/in/aayushroka77',
    photo: aayushPhoto,
  },
  {
    id: 1,
    name: 'Bishesh Khanal',
    email: 'bisheshkhanal036@gmail.com',
    linkedin: 'https://www.linkedin.com/in/bisheshkhanal',
    photo: bisheshPhoto,
  },
  {
    id: 3,
    name: 'Anuj Thapa',
    email: 'anujthapaclass10@gmail.com',
    linkedin: 'https://www.linkedin.com/in/anuj-thapa-6a4066317',
    photo: anujPhoto,
  },
]
