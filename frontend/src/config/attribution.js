// Static credits content for the landing page's Credits section and the
// in-tool About modal (Sidebar.jsx). This is deliberately NOT a live API
// call: the landing page is shown before any AOI/compute exists, so
// there is no request in flight yet to read attribution off of.
//
// SOURCE_ATTRIBUTIONS below are copied VERBATIM from
// backend/app/data/attribution.py's own constants (DEM_ATTRIBUTION,
// WORLDCOVER_ATTRIBUTION, OSM_ATTRIBUTION) -- the same strings
// ResultPanel already renders from a live compute response's
// `result.attribution`. If those backend constants ever change, this
// file needs a matching update to stay in sync (there's no automated
// link between the two, since this file exists precisely so the credits
// page doesn't need a backend round-trip).
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

// Methodology citations (Saaty/AHP, Random Index source, drainage-density
// technique reference) deliberately left out of the Credits section for
// now, at the user's request ("don't cite papers yet") -- the full,
// correct bibliographic details (especially for the drainage-density
// reference, currently only an informal "the Siraha paper" mention in
// backend/app/data/hydrology.py with no author list/journal/DOI anywhere
// in this codebase) need to be supplied before this goes back in, rather
// than publishing a citation this project can't fully stand behind yet.

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

export const TEAM_CREDITS = [
  {
    id: 1,
    name: 'Bishesh Khanal',
    email: 'bisheshkhanal036@gmail.com',
    linkedin: 'https://www.linkedin.com/in/bisheshkhanal',
    photo: bisheshPhoto,
  },
  {
    id: 2,
    name: 'Aayush Roka',
    email: 'er.rokaayush77@gmail.com',
    linkedin: 'https://www.linkedin.com/in/aayushroka77',
    photo: aayushPhoto,
  },
  {
    id: 3,
    name: 'Anuj Thapa',
    email: 'anujthapaclass10@gmail.com',
    linkedin: 'https://www.linkedin.com/in/anuj-thapa-6a4066317',
    photo: anujPhoto,
  },
]
