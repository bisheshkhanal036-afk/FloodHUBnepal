"""Exception types raised by the geospatial data layer."""

from __future__ import annotations


class DataSourceUnavailableError(RuntimeError):
    """No path — local or cloud — could serve this request.

    Raised only where silently falling through to something slow/
    unreliable (e.g. the live Overpass API for OSM) would be worse than
    a clear failure. DEM and WorldCover never raise this: their cloud
    fallback (public, anonymous S3 COG reads) is treated as always
    available, so a network failure there surfaces as whatever the
    underlying read raised, not this.
    """


class NodataValidationError(ValueError):
    """A processed raster's nodata value is missing, inconsistent, or
    otherwise unsafe to proceed with — see SPEC.md, "Nodata handling".
    """


class ReclassificationError(ValueError):
    """A criterion's reclassification_rules are malformed (gaps/overlaps),
    or a data value didn't match any rule at apply time.
    """


class BasinNotFoundError(ValueError):
    """The HydroBASINS dataset loaded successfully, but no basin with the
    requested HYBAS_ID exists in it. Distinct from
    DataSourceUnavailableError, which is for the dataset itself being
    missing/unreadable/wrong-shaped — this is "the data's fine, that ID
    just isn't in it" (a 404, not a 503).
    """


class DistrictNotFoundError(ValueError):
    """Mirrors BasinNotFoundError, for app/data/districts.py: the admin
    boundaries file loaded successfully, but no district with the
    requested pcode exists in it — a 404, not a 503.
    """
