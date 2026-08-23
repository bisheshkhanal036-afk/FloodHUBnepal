"""Part 2 of the vulnerability-classification feature: tag each OSM
building with the discrete hazard class (1-5) its footprint falls in.

Sampling rule: MAJORITY-OVERLAP, not centroid. A building's centroid is
simpler and marginally faster, but a large or elongated building can
genuinely straddle a hazard-class boundary (this project's 10m grid
means even a modest building can span several pixels) -- centroid
sampling would then report whichever class happens to contain one
specific point, arbitrary from the building's own perspective, while
majority-overlap reports which class actually covers most of the
building's real footprint. Implemented so this isn't much more
expensive than centroid sampling despite doing more real work: ONE
labeled rasterize pass (every building's footprint rasterized at once
into a single "which building owns this pixel" raster, not one
rasterize call per building) followed by a single vectorized groupby-
mode over the flattened (building_label, hazard_class) pairs -- O(n
buildings + n pixels), not O(n buildings) separate raster operations.

Ties (a footprint split evenly between two classes) resolve to the
HIGHER class -- the more conservative reading for a hazard report,
consistent with this project's general "never understate risk" stance
(the same reasoning a nodata pixel in any contributing criterion
already gets treated as excluded rather than assumed low-risk,
compute.compute_risk_surface's any_nodata handling).

A building too small to rasterize to any pixel at all under its own
label (its footprint's centroid-ish area smaller than the 10m grid can
resolve) falls back to a direct centroid sample -- not left unclassified
just because majority-overlap's own mechanism has nothing to count.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from rasterio.transform import rowcol

from app.data.grid import AOIGrid

from .hazard_classes import HAZARD_CLASS_LABELS, HAZARD_CLASS_NODATA


@dataclass(frozen=True)
class ClassifiedBuilding:
    geometry: object  # a shapely geometry, in `buildings`' OWN original CRS (EPSG:4326 in production) -- see classify_buildings
    hazard_class: int | None  # None means "outside the AOI / no data at this location", not "class 0"
    hazard_label: str | None


def _centroid_hazard_class(centroid, transform, hazard_class_raster: np.ndarray) -> int | None:
    height, width = hazard_class_raster.shape
    row, col = rowcol(transform, centroid.x, centroid.y)
    if not (0 <= row < height and 0 <= col < width):
        return None
    value = int(hazard_class_raster[row, col])
    return value if value != HAZARD_CLASS_NODATA else None


def classify_buildings(
    buildings: gpd.GeoDataFrame, grid: AOIGrid, hazard_class_raster: np.ndarray
) -> list[ClassifiedBuilding]:
    """`buildings` is normally get_osm_features(aoi).buildings — real OSM
    geometries, always EPSG:4326 in production — reprojected to `grid`'s
    CRS internally for the spatial join, but `buildings`' OWN original
    CRS/geometry (whatever it actually is, not assumed to be EPSG:4326)
    is what each ClassifiedBuilding carries back out, since the GeoJSON
    callers want is naturally in the same CRS every other GeoJSON this
    API returns is.
    """
    if len(buildings) == 0:
        return []

    projected = buildings.to_crs(grid.crs) if str(buildings.crs) != grid.crs else buildings
    geoms_utm = list(projected.geometry)
    geoms_original_crs = list(buildings.geometry)

    # Every building gets a unique positive label (1-indexed: 0 stays
    # "no building here", matching HAZARD_CLASS_NODATA/RECLASSIFIED_
    # NODATA's own "0 = nothing" convention throughout this codebase).
    # int32, not uint8/16: a real Kathmandu-Valley-sized AOI can hold
    # well over 65,535 buildings (verified live earlier this session --
    # over 350,000 in one bbox), which uint16 can't label uniquely.
    label_raster = rasterize(
        ((geom, i + 1) for i, geom in enumerate(geoms_utm) if geom is not None and not geom.is_empty),
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        fill=0,
        all_touched=False,
        dtype=np.int32,
    )

    covered_labels = label_raster[label_raster != 0]
    covered_classes = hazard_class_raster[label_raster != 0]
    majority_by_label: dict[int, int] = {}
    if covered_labels.size > 0:
        df = pd.DataFrame({"label": covered_labels, "hazard_class": covered_classes})
        df = df[df["hazard_class"] != HAZARD_CLASS_NODATA]
        if len(df) > 0:
            # value_counts is already sorted by count descending; a tie
            # (equal counts) keeps pandas' own tie-break, which is first-
            # seen -- NOT guaranteed to be the higher class. Re-sort by
            # (count desc, hazard_class desc) explicitly so a genuine tie
            # resolves to the higher class, per this module's own
            # documented "never understate risk" tie-break rule.
            counts = df.groupby(["label", "hazard_class"]).size().reset_index(name="count")
            counts = counts.sort_values(["label", "count", "hazard_class"], ascending=[True, False, False])
            majority_by_label = counts.drop_duplicates(subset="label", keep="first").set_index("label")[
                "hazard_class"
            ].to_dict()

    results: list[ClassifiedBuilding] = []
    for i, (geom_utm, geom_original) in enumerate(zip(geoms_utm, geoms_original_crs)):
        label = i + 1
        if geom_utm is None or geom_utm.is_empty:
            results.append(ClassifiedBuilding(geometry=geom_original, hazard_class=None, hazard_label=None))
            continue

        hazard_class = majority_by_label.get(label)
        if hazard_class is None:
            # Too small to rasterize to any labeled pixel -- fall back to
            # a direct centroid sample rather than leaving it unclassified.
            hazard_class = _centroid_hazard_class(geom_utm.centroid, grid.transform, hazard_class_raster)

        label_str = HAZARD_CLASS_LABELS.get(hazard_class) if hazard_class is not None else None
        results.append(ClassifiedBuilding(geometry=geom_original, hazard_class=hazard_class, hazard_label=label_str))

    return results
