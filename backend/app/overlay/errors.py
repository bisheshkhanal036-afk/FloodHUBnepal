"""Exception types raised by the overlay engine."""

from __future__ import annotations


class OverlayValidationError(ValueError):
    """The overlay request is structurally invalid or the AHP weight set
    isn't safe to combine — incomplete weights (don't sum to 1), a
    criteria/weights mismatch, an unrecognized criterion source, or a
    grid mismatch between two criteria rasters for the same AOI. Never
    raised for a data-fetch failure (Phase 2's own errors propagate
    as-is) — only for problems with the overlay request itself.
    """
