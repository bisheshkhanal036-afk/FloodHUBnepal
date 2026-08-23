"""Part 3 of the vulnerability-classification feature: per-hazard-class
zonal statistics (area, population, building count) -- the actual
numeric core of the Siraha-style report.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.data.grid import AOIGrid

from .building_classification import ClassifiedBuilding
from .hazard_classes import HAZARD_CLASS_LABELS


@dataclass(frozen=True)
class ZonalClassStats:
    hazard_class: int
    hazard_label: str
    area_km2: float
    population: float
    building_count: int


def compute_zonal_stats(
    hazard_class_raster: np.ndarray,
    grid: AOIGrid,
    population_density: np.ndarray,
    population_nodata: float,
    classified_buildings: list[ClassifiedBuilding],
) -> list[ZonalClassStats]:
    """One ZonalClassStats per hazard class 1-5, always all 5 present
    (zero-filled if a class has no pixels in this AOI) -- a report caller
    should never have to guess whether a missing class means "zero" or
    "not computed".

    `population_density` MUST be a density field (people/km²), not a raw
    count -- see app/data/population.py's own docstring for why HRSL's
    native data has to be converted before it's usable this way at all.
    Population per class is therefore Σ(density * pixel_area_km2) over
    that class's pixels, not a raw Σ(density) -- summing density values
    directly would silently be off by a factor of pixel_area_km2 (a
    ~0.0001 km² number at this grid's 10m resolution), the same unit
    mistake population.py's own _count_to_density fix was written to
    prevent one layer up. A population-nodata pixel (HRSL has no data
    there, e.g. open water) contributes 0 to the sum, not excluded from
    the class's area/building count -- absence of population data isn't
    absence of the pixel itself.
    """
    pixel_area_km2 = (grid.resolution_m**2) / 1e6

    building_count_by_class: dict[int, int] = {c: 0 for c in HAZARD_CLASS_LABELS}
    for b in classified_buildings:
        if b.hazard_class is not None:
            building_count_by_class[b.hazard_class] += 1

    population_valid = population_density != population_nodata
    population_contribution = np.where(population_valid, population_density, 0.0) * pixel_area_km2

    results = []
    for hazard_class, label in HAZARD_CLASS_LABELS.items():
        class_mask = hazard_class_raster == hazard_class
        pixel_count = int(np.count_nonzero(class_mask))
        results.append(
            ZonalClassStats(
                hazard_class=hazard_class,
                hazard_label=label,
                area_km2=pixel_count * pixel_area_km2,
                population=float(np.sum(population_contribution[class_mask])) if pixel_count else 0.0,
                building_count=building_count_by_class[hazard_class],
            )
        )
    return results
