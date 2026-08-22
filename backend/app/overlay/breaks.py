"""Computes candidate reclassification break points — equal-interval,
quantile, and Jenks natural breaks — for one criterion's raw
(not-yet-reclassified) values over one AOI. Lets the frontend offer the
user data-driven starting points for `reclassification_rules` instead of
only this app's static defaults, and a "manual" option that needs no
computation at all — just the criterion's actual value range for
context.

Reuses the exact same registry (sources.py) the overlay engine itself
resolves a criterion's raw layer through — a 9th/10th/... criterion
source registered there gets this for free too, no changes needed here.

NUM_CLASSES is fixed at 5, matching schemas/criterion.schema.json's
reclassificationRule.risk_class range (1-5) — not a parameter a caller
can vary.
"""

from __future__ import annotations

import numpy as np

from app.data.aoi import AOI

from .errors import OverlayValidationError
from .sources import _raw_layer_for_source

NUM_CLASSES = 5

# Fisher-Jenks is at least O(n*k); on a large AOI's full pixel
# population (up to ~10,000,000 at the 1000km^2/10m cap) that's still slow
# enough to matter for a live UI control. Capped to a deterministic
# (fixed-seed) sample of this many valid pixels before running Jenks --
# the same practice QGIS's own "Natural Breaks (Jenks)" classifier uses
# for large rasters (a systematic/random sample, not the full
# population). Equal-interval and quantile don't need this: both are
# fast even on millions of points and are always computed from the FULL
# valid-pixel population, not a sample.
JENKS_SAMPLE_SIZE = 10_000
_JENKS_SAMPLE_SEED = 0  # fixed, so the same (aoi, source) always gets the same Jenks breaks


def _valid_values(raw: np.ndarray, nodata) -> np.ndarray:
    """Mirrors reclassify.apply_reclassification's own nodata-matching
    convention exactly (None = every pixel valid; NaN-aware; else exact
    equality) so "valid" here always means the same thing it will mean
    when these values are actually reclassified.
    """
    flat = raw.ravel().astype(np.float64)
    if nodata is None:
        return flat
    if isinstance(nodata, float) and np.isnan(nodata):
        return flat[~np.isnan(flat)]
    return flat[flat != nodata]


def _equal_interval_breaks(values: np.ndarray) -> list[float]:
    edges = np.linspace(float(values.min()), float(values.max()), NUM_CLASSES + 1)
    return [float(v) for v in edges[1:-1]]


def _quantile_breaks(values: np.ndarray) -> list[float]:
    percentiles = np.linspace(0, 100, NUM_CLASSES + 1)[1:-1]
    return [float(v) for v in np.percentile(values, percentiles)]


def _jenks_breaks(values: np.ndarray) -> list[float]:
    import jenkspy

    sample = values
    if sample.size > JENKS_SAMPLE_SIZE:
        rng = np.random.default_rng(_JENKS_SAMPLE_SEED)
        sample = rng.choice(sample, size=JENKS_SAMPLE_SIZE, replace=False)
    # jenks_breaks needs at least n_classes+1 distinct values to produce
    # n_classes real bins; a pathological (near-)constant AOI falls back
    # to equal-interval instead of letting jenkspy raise.
    if np.unique(sample).size <= NUM_CLASSES:
        return _equal_interval_breaks(values)
    edges = jenkspy.jenks_breaks(sample.tolist(), n_classes=NUM_CLASSES)
    return [float(v) for v in edges[1:-1]]


def compute_criterion_breaks(aoi: AOI, source: str) -> dict:
    """Returns {min, max, valid_pixel_count, equal_interval, quantile,
    jenks} for `source` over `aoi` — the last 3 are each a list of 4
    interior break values (5 classes need 4 interior edges; the outer
    ends are always unbounded, matching every reclassification_rules
    array already in this project). Raises OverlayValidationError (via
    _raw_layer_for_source, same as the overlay compute path) for an
    unrecognized source, and if the AOI has literally no valid pixels
    for this source at all.
    """
    raw, _grid, nodata, _attribution, _warning = _raw_layer_for_source(aoi, source)
    values = _valid_values(raw, nodata)
    if values.size == 0:
        raise OverlayValidationError(f"no valid (non-nodata) pixels for source {source!r} over this AOI")

    return {
        "min": float(values.min()),
        "max": float(values.max()),
        "valid_pixel_count": int(values.size),
        "equal_interval": _equal_interval_breaks(values),
        "quantile": _quantile_breaks(values),
        "jenks": _jenks_breaks(values),
    }
