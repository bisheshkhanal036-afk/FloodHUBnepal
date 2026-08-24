// Literature & methodology documentation for every criterion (feature)
// used in the flood-risk overlay, surfaced in the UI via a per-feature
// info (ⓘ) button that opens LiteratureModal. For each feature:
//   whatItIs   -- the physical/derived quantity and its unit
//   floodRole  -- why it conditions flood risk, and the risk direction
//   rangeBasis -- how the 5-class reclassification ranges are set + basis
//   refs       -- keys into REFERENCES (rendered as a per-feature reading list)
//
// IMPORTANT (academic integrity): the citations below are genuine,
// well-established works in the flood-susceptibility / AHP and remote-
// sensing literature, provided for methodological transparency. The exact
// numeric class breaks in src/config/criteria.js are, as is standard in
// index-based AHP flood mapping, expert-defined for the Kathmandu Valley
// study area and should be re-calibrated against a local flood inventory
// before any formal publication — see the "How the ranges are set"
// note in each entry and REFERENCES.das2019 / REFERENCES.kazakis2015 for
// the general reclassify-into-5-classes practice this follows.

export const METHOD_INTRO = {
  title: 'Method & how to read this',
  body: [
    'FloodHUB maps flood risk with the Analytic Hierarchy Process (AHP), a multi-criteria decision method (Saaty, 1980). Each conditioning factor below is reprojected onto a common 10 m grid, reclassified into five ordinal risk classes (1 = lowest, 5 = highest), and combined as a weighted sum: R = Σ (wᵢ × classᵢ), where the weights wᵢ come from pairwise expert comparisons on Saaty’s 1–9 scale and are checked for logical consistency (Consistency Ratio < 0.10).',
    'The reclassification ranges turn each factor’s continuous or categorical values into those five classes. Following standard index-based flood-susceptibility practice (Kazakis et al., 2015; Das, 2019; Tehrany et al., 2014), the class breaks are set from the physical behaviour of each factor and the local terrain, then refined by expert judgment; they are editable per criterion in the “Customize breaks” panel. For rigorous use they should be validated against an observed flood inventory (success-rate / AUC).',
  ],
  refs: ['saaty1980', 'kazakis2015', 'das2019', 'tehrany2014'],
}

export const LITERATURE = {
  // ---------------- Topographic ----------------
  dem_elevation: {
    whatItIs:
      'Ground-surface elevation above sea level (metres), from the Copernicus GLO-30 DEM resampled to 10 m.',
    floodRole:
      'Low-lying ground accumulates surface and channel water and is inundated first; flood risk therefore decreases as elevation increases. Elevation is one of the most widely used flood-conditioning factors (Kazakis et al., 2015; Tehrany et al., 2014).',
    rangeBasis:
      'Breaks are set relative to the Kathmandu Valley floor (~1,300–1,350 m): the lowest tier (highest risk) captures the valley-bottom / floodplain, with successively higher elevation bands assigned lower risk. Absolute thresholds are study-area specific and expert-defined, as is standard in AHP flood mapping (Das, 2019).',
    refs: ['kazakis2015', 'tehrany2014', 'das2019', 'copernicusdem'],
  },
  dem_slope: {
    whatItIs:
      'Terrain slope in degrees (Horn’s method) computed from the DEM.',
    floodRole:
      'Gentle slopes drain slowly and let water pond and spread, so flood risk decreases as slope steepens; steep terrain sheds water rapidly. Slope is a standard conditioning factor in flood-susceptibility models (Fernández & Lutz, 2010; Rahmati et al., 2016).',
    rangeBasis:
      'Flattest terrain is assigned the highest risk class, with risk declining across increasing slope bands. Degree thresholds are set from the valley’s low-relief floor vs. its surrounding hills and are expert/literature-guided rather than universal (Kazakis et al., 2015).',
    refs: ['fernandez2010', 'rahmati2016', 'kazakis2015'],
  },
  twi: {
    whatItIs:
      'Topographic Wetness Index, TWI = ln(a / tan β), where a is the upslope contributing area per unit contour length and β is the local slope (Beven & Kirkby, 1979).',
    floodRole:
      'TWI quantifies the tendency of a cell to accumulate water from its catchment; higher TWI marks wetter, saturation-prone, flood-susceptible ground, so risk increases with TWI. It is a core hydrological terrain index (Sørensen et al., 2006).',
    rangeBasis:
      'Higher TWI values map to higher risk classes. Because TWI is dimensionless and its distribution depends on DEM resolution and the flow-routing algorithm, class breaks are set on the observed value range for the AOI (Sørensen et al., 2006).',
    refs: ['bevenkirkby1979', 'sorensen2006'],
  },
  hand: {
    whatItIs:
      'Height Above Nearest Drainage (metres): the vertical drop from each cell down its flow path to the nearest stream channel (Rennó et al., 2008; Nobre et al., 2011).',
    floodRole:
      'HAND normalizes elevation to the local drainage network and is a strong, physically motivated proxy for inundation potential — low HAND means the cell sits only slightly above (and hydrologically close to) a channel, so flood risk decreases as HAND increases (Nobre et al., 2011, 2016).',
    rangeBasis:
      'The lowest HAND band (near channel level) is highest risk, with risk falling as vertical separation from the drainage grows. Thresholds echo HAND flood-mapping studies that treat a few metres above drainage as the inundation-prone zone (Nobre et al., 2016).',
    refs: ['renno2008', 'nobre2011', 'nobre2016'],
  },
  // ---------------- Hydrological ----------------
  rainfall: {
    whatItIs:
      'Mean annual maximum 1-day precipitation (Rx1day, mm) — an ETCCDI extreme-precipitation index computed from the Department of Hydrology and Meteorology daily gauge record (1980–2022, 254 quality-controlled stations) and interpolated to the analysis grid by inverse distance weighting.',
    floodRole:
      'Rainfall is the flood trigger: every other criterion in this model describes the terrain, land cover or exposure that converts rain into a flood, but precipitation is what supplies the water. Short-duration extreme rainfall in particular drives flash and pluvial flooding, so risk increases with Rx1day. Precipitation is one of the two most heavily weighted factors in the reference method for this project (Parajuli et al., 2023) and is standard in index-based flood-susceptibility models (Kazakis et al., 2015; Tehrany et al., 2014).',
    rangeBasis:
      'Unlike most criteria here, these breaks are not expert-set: they are the observed quintiles of Rx1day across all 254 gauges (80, 96, 124 and 151 mm), so each class holds one fifth of the national gauge distribution. Rx1day is the default index because short-duration extremes drive flooding; switch RAINFALL_VARIABLE to PRCPTOT for direct comparison with the reference paper’s annual precipitation factor. Interpolation is elevation-blind, so values in steep terrain carry a warning on the result.',
    refs: ['parajuli2023', 'kazakis2015', 'tehrany2014', 'zhang2011etccdi', 'dhm'],
  },
  precipitation_chirps: {
    whatItIs:
      'Mean annual precipitation (mm/yr), a 1981–2024 climatology from CHIRPS (Climate Hazards group InfraRed Precipitation with Station data) — a satellite-derived, quasi-global rainfall estimate that itself blends infrared cold-cloud-duration imagery with station data (Funk et al., 2015), read at its native ~0.05° (~5.5 km) grid.',
    floodRole:
      'Like "Rainfall", this is a flood-trigger factor, not a terrain or exposure one — precipitation is what supplies the water every other criterion turns into a flood (Parajuli et al., 2023). It is registered as a second, independent precipitation estimate rather than a replacement for the DHM-gauge "Rainfall" criterion: the two fail differently. "Rainfall" is interpolated (IDW) from 254 point gauges and is elevation-blind, degrading with distance from the nearest one; CHIRPS is a dense, gapless grid that never depends on gauge proximity, but satellite infrared retrievals carry their own known bias over high, complex, snow-covered terrain — exactly the terrain much of Nepal is. Risk increases with precipitation in both criteria.',
    rangeBasis:
      'Placeholder equal-interval-ish breaks (1000 / 1800 / 2600 / 3400 mm/yr), derived from real CHIRPS values sampled across Nepal’s actual climate range rather than guessed: from the dry western hills (Jumla, ~670 mm/yr) to the wet mid-hills (Pokhara, ~3,340 mm/yr), with Kathmandu Valley (~1,490 mm/yr) and the Terai plains (~1,890 mm/yr) both sitting mid-range. Like every other criterion here, these are a starting point pending calibration against an observed flood inventory, not a literature-derived threshold set.',
    refs: ['funk2015', 'parajuli2023', 'kazakis2015', 'tehrany2014'],
  },
  dist_to_river: {
    whatItIs:
      'Euclidean distance (metres) from each cell to the nearest river / stream / canal, from OpenStreetMap waterways.',
    floodRole:
      'Proximity to a watercourse increases exposure to channel overflow and bank inundation, so flood risk decreases with distance from rivers — a consistently high-weight factor in flood studies (Das, 2019; Rahmati et al., 2016).',
    rangeBasis:
      'The nearest buffer (highest risk) reflects the typical channel-overflow / riparian zone, with risk declining over successively wider distance bands. Buffer widths are expert-set for the valley’s stream scale (Das, 2019).',
    refs: ['das2019', 'rahmati2016'],
  },
  drainage_density: {
    whatItIs:
      'Local drainage density (km of stream channel per km²) within a moving window, derived from the extracted stream network (concept: Melton, 1957).',
    floodRole:
      'Denser channel networks concentrate and deliver runoff faster to a location, raising flood potential, so risk increases with drainage density (Das, 2019).',
    rangeBasis:
      'Higher density maps to higher risk. Class breaks span the AOI’s observed density range; the absolute values depend on the stream-extraction threshold and window radius and are treated as expert/calibratable parameters (Melton, 1957; Das, 2019).',
    refs: ['melton1957', 'das2019'],
  },
  // ---------------- Land Use ----------------
  worldcover_land_cover: {
    whatItIs:
      'ESA WorldCover 10 m land-cover class (Zanaga et al., 2022): built-up, cropland, tree cover, water, wetland, etc.',
    floodRole:
      'Land cover governs infiltration vs. runoff and what is exposed: impervious built-up surfaces, open water and wetlands score highest risk, while tree cover — high infiltration, high roughness — scores lowest. Land use/land cover is a standard flood-conditioning factor (Tehrany et al., 2014).',
    rangeBasis:
      'This is categorical, so each WorldCover legend code is assigned a risk class directly from its hydrological behaviour (built-up/water/wetland → 5; tree cover → 1), rather than from numeric ranges (Zanaga et al., 2022; Tehrany et al., 2014).',
    refs: ['zanaga2022', 'tehrany2014'],
  },
  ndvi: {
    whatItIs:
      'Normalized Difference Vegetation Index, NDVI = (NIR − Red) / (NIR + Red), in [−1, 1], from Sentinel-2 (Rouse et al., 1974).',
    floodRole:
      'Vigorous vegetation intercepts rainfall, boosts infiltration and surface roughness, and stabilizes soil — reducing and slowing runoff. Low or negative NDVI (bare soil, built-up, water) sheds water faster, so flood risk decreases as NDVI increases (Rouse et al., 1974; Tehrany et al., 2014).',
    rangeBasis:
      'Low NDVI is assigned the highest risk, decreasing to lowest risk for dense vegetation. Breaks follow common NDVI interpretation bands (water/built < 0.1; sparse to dense vegetation upward) and are adjustable for the season and sensor (Rouse et al., 1974).',
    refs: ['rouse1974', 'tehrany2014'],
  },
  soil_infiltration: {
    whatItIs:
      'Topsoil (0–5 cm) sand content (%), from ISRIC SoilGrids 2.0 (Poggio et al., 2021), used as a proxy for soil infiltration capacity.',
    floodRole:
      'Soil texture governs how quickly rainfall infiltrates versus runs off: coarser, sandier soils have higher hydraulic conductivity and infiltration capacity than finer-textured soils (Rawls, Brakensiek, & Saxton, 1982) — the same texture–permeability relationship USDA Hydrologic Soil Group classification is built on (NRCS, 2007). Higher sand content therefore means faster drainage and less runoff generation, so flood risk decreases as sand content increases. Soil type/permeability is a recognized conditioning factor in both index-based and machine-learning flood-susceptibility mapping (Chapi et al., 2017).',
    rangeBasis:
      'Class breaks are equal intervals across SoilGrids’ 0–100% sand-content range, with the lowest-sand (finest-textured, least permeable) band assigned the highest risk. This is a simplified single-property proxy, not a full USDA Hydrologic Soil Group — that would also incorporate clay content via the standard texture-triangle lookup — and, as with every criterion here, the breaks are a placeholder pending calibration (NRCS, 2007).',
    refs: ['poggio2021', 'rawls1982', 'nrcs2007', 'chapi2017'],
  },
  // ---------------- Infrastructure ----------------
  dist_to_road: {
    whatItIs:
      'Euclidean distance (metres) from each cell to the nearest road, from the OpenStreetMap road network.',
    floodRole:
      'This is an accessibility / response factor rather than a hazard driver: areas far from roads are harder to evacuate, reach with relief, and drain via engineered infrastructure, so modelled risk increases with distance from roads. It reflects the exposure/coping dimension of disaster risk (IPCC, 2012).',
    rangeBasis:
      'Nearest roads are lowest risk and remote areas highest, over increasing distance bands sized to the valley’s settlement/road spacing. Because this encodes accessibility judgment, its class breaks and weight are deliberately editable (IPCC, 2012).',
    refs: ['ipcc2012', 'fernandez2010'],
  },
  // ---------------- Exposure ----------------
  building_density: {
    whatItIs:
      'Local building-footprint coverage fraction (0–1) within a moving window, from OpenStreetMap building polygons.',
    floodRole:
      'An exposure factor: denser building clusters mean more people and property at risk if flooded, and more impervious surface generating runoff, so risk increases with building density. Exposure is a core term of disaster risk (risk = hazard × exposure × vulnerability; IPCC, 2012).',
    rangeBasis:
      'Higher coverage maps to higher risk. Fractional breaks (e.g. sparse < 0.15 to dense > 0.6) are set from urban-form judgment for the valley and are calibratable (Cutter et al., 2003; IPCC, 2012).',
    refs: ['ipcc2012', 'cutter2003'],
  },
  population_density: {
    whatItIs:
      'Population density from the Meta / CIESIN High Resolution Settlement Layer (HRSL), resampled to the analysis grid.',
    floodRole:
      'A direct exposure/social-vulnerability factor: the more people present, the greater the potential human impact of a flood, so risk increases with population density (Cutter et al., 2003; Rufat et al., 2015).',
    rangeBasis:
      'Higher population density maps to higher risk. Because HRSL density is highly skewed, class breaks are set on its distribution over the AOI (e.g. natural-breaks / quantiles) rather than fixed absolute counts (Rufat et al., 2015).',
    refs: ['cutter2003', 'rufat2015', 'hrsl'],
  },
}

// Curated bibliography. Keys are referenced by METHOD_INTRO/LITERATURE.
export const REFERENCES = {
  parajuli2023:
    'Parajuli, G., Neupane, S., Kunwar, S., Adhikari, R., & Acharya, T. D. (2023). A GIS-Based Evacuation Route Planning in Flood-Susceptible Area of Siraha Municipality, Nepal. ISPRS International Journal of Geo-Information, 12(7), 286. https://doi.org/10.3390/ijgi12070286',
  zhang2011etccdi:
    'Zhang, X., Alexander, L., Hegerl, G. C., Jones, P., Tank, A. K., Peterson, T. C., Trewin, B., & Zwiers, F. W. (2011). Indices for monitoring changes in extremes based on daily temperature and precipitation data. WIREs Climate Change, 2(6), 851–870.',
  dhm:
    'Department of Hydrology and Meteorology (DHM), Government of Nepal. Daily precipitation records, 1980–2022, national rain-gauge network.',
  funk2015:
    'Funk, C., Peterson, P., Landsfeld, M., Pedreros, D., Verdin, J., Shukla, S., Husak, G., Rowland, J., Harrison, L., Hoell, A., & Michaelsen, J. (2015). The climate hazards infrared precipitation with stations—a new environmental record for monitoring extremes. Scientific Data, 2, 150066. https://doi.org/10.1038/sdata.2015.66',
  saaty1980:
    'Saaty, T. L. (1980). The Analytic Hierarchy Process: Planning, Priority Setting, Resource Allocation. McGraw-Hill, New York.',
  kazakis2015:
    'Kazakis, N., Kougias, I., & Patsialis, T. (2015). Assessment of flood hazard areas at a regional scale using an index-based approach and Analytical Hierarchy Process: Application in Rhodope–Evros region, Greece. Science of the Total Environment, 538, 555–563.',
  das2019:
    'Das, S. (2019). Geospatial mapping of flood susceptibility and hydro-geomorphic response to the floods in Ulhas basin, India. Remote Sensing Applications: Society and Environment, 14, 60–74.',
  tehrany2014:
    'Tehrany, M. S., Pradhan, B., & Jebur, M. N. (2014). Flood susceptibility mapping using a novel ensemble weights-of-evidence and support vector machine models in GIS. Journal of Hydrology, 512, 332–343.',
  rahmati2016:
    'Rahmati, O., Zeinivand, H., & Besharat, M. (2016). Flood hazard zoning in Yasooj region, Iran, using GIS and multi-criteria decision analysis. Geomatics, Natural Hazards and Risk, 7(3), 1000–1017.',
  fernandez2010:
    'Fernández, D. S., & Lutz, M. A. (2010). Urban flood hazard zoning in Tucumán Province, Argentina, using GIS and multicriteria decision analysis. Engineering Geology, 111(1–4), 90–98.',
  bevenkirkby1979:
    'Beven, K. J., & Kirkby, M. J. (1979). A physically based, variable contributing area model of basin hydrology. Hydrological Sciences Bulletin, 24(1), 43–69.',
  sorensen2006:
    'Sørensen, R., Zinko, U., & Seibert, J. (2006). On the calculation of the topographic wetness index: evaluation of different methods based on field observations. Hydrology and Earth System Sciences, 10(1), 101–112.',
  renno2008:
    'Rennó, C. D., Nobre, A. D., Cuartas, L. A., Soares, J. V., Hodnett, M. G., Tomasella, J., & Waterloo, M. J. (2008). HAND, a new terrain descriptor using SRTM-DEM: Mapping terra-firme rainforest environments in Amazonia. Remote Sensing of Environment, 112(9), 3469–3481.',
  nobre2011:
    'Nobre, A. D., Cuartas, L. A., Hodnett, M., Rennó, C. D., Rodrigues, G., Silveira, A., Waterloo, M., & Saleska, S. (2011). Height Above the Nearest Drainage – a hydrologically relevant new terrain model. Journal of Hydrology, 404(1–2), 13–29.',
  nobre2016:
    'Nobre, A. D., Cuartas, L. A., Momo, M. R., Severo, D. L., Pinheiro, A., & Nobre, C. A. (2016). HAND contour: a new proxy predictor of inundation extent. Hydrological Processes, 30(2), 320–333.',
  rouse1974:
    'Rouse, J. W., Haas, R. H., Schell, J. A., & Deering, D. W. (1974). Monitoring vegetation systems in the Great Plains with ERTS. NASA Special Publication SP-351, 309–317.',
  melton1957:
    'Melton, M. A. (1957). An analysis of the relations among elements of climate, surface properties, and geomorphology. Technical Report 11, Office of Naval Research, Columbia University.',
  cutter2003:
    'Cutter, S. L., Boruff, B. J., & Shirley, W. L. (2003). Social vulnerability to environmental hazards. Social Science Quarterly, 84(2), 242–261.',
  rufat2015:
    'Rufat, S., Tate, E., Burton, C. G., & Maroof, A. S. (2015). Social vulnerability to floods: Review of case studies and implications for measurement. International Journal of Disaster Risk Reduction, 14, 470–486.',
  ipcc2012:
    'IPCC (2012). Managing the Risks of Extreme Events and Disasters to Advance Climate Change Adaptation (SREX). Field, C. B., et al. (eds.). Cambridge University Press.',
  zanaga2022:
    'Zanaga, D., Van De Kerchove, R., Daems, D., et al. (2022). ESA WorldCover 10 m 2021 v200. Zenodo. https://doi.org/10.5281/zenodo.7254221',
  copernicusdem:
    'European Space Agency & Airbus (2022). Copernicus DEM — Global and European Digital Elevation Model (GLO-30). Copernicus Space Component data access.',
  hrsl:
    'Meta & CIESIN, Columbia University (2022). High Resolution Settlement Layer (HRSL). Source imagery © 2016 Maxar. https://registry.opendata.aws/dataforgood-fb-hrsl/',
  poggio2021:
    'Poggio, L., de Sousa, L. M., Batjes, N. H., Heuvelink, G. B. M., Kempen, B., Ribeiro, E., & Rossiter, D. (2021). SoilGrids 2.0: producing soil information for the globe with quantified spatial uncertainty. SOIL, 7, 217–240. https://doi.org/10.5194/soil-7-217-2021',
  rawls1982:
    'Rawls, W. J., Brakensiek, D. L., & Saxton, K. E. (1982). Estimation of soil water properties. Transactions of the ASAE, 25(5), 1316–1320.',
  nrcs2007:
    'USDA Natural Resources Conservation Service (2007). National Engineering Handbook, Part 630 Hydrology, Chapter 7: Hydrologic Soil Groups.',
  chapi2017:
    'Chapi, K., Singh, V. P., Shirzadi, A., Shahabi, H., Bui, D. T., Pham, B. T., & Khosravi, K. (2017). A novel hybrid artificial intelligence approach for flood susceptibility assessment. Environmental Modelling & Software, 95, 229–245.',
}
