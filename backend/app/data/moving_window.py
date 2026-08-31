"""Circular moving-window sums, shared by the two density criteria.

`density_raster.py` (building coverage) and `hydrology.py` (drainage
density) both compute the same thing: for every cell, the sum of some
quantity over a circular neighbourhood of a configured radius. Each
module's docstring already described the other's as "the same
construction"; this is that construction, written once.

--- Why FFT convolution and not scipy.ndimage.convolve ---

Both modules previously used `scipy.ndimage.convolve`, which performs
*direct* spatial convolution -- for every output cell it touches every
kernel cell. That is fine while the kernel is small relative to the
image and degenerates badly when it is not, which is exactly the regime
these criteria run in: the window radius is a real-world distance
(hundreds to thousands of metres) while an AOI can be small, so the
kernel routinely ends up **larger than the raster it is applied to**.

Measured in this container on a 68x61 test grid:

    window radius   kernel      scipy.ndimage.convolve
    200 m (bldg)    41x41       0.07 s,    77 MB
    500 m (drain)   101x101     0.97 s,   309 MB
    800 m           161x161     1.85 s,   697 MB
    1200 m          241x241    11.48 s,  1493 MB
    2000 m          401x401    OOM-killed

The same operation via `scipy.signal.fftconvolve`:

    200 m           41x41       0.00 s,    92 MB
    500 m           101x101     0.00 s,    93 MB
    2000 m          401x401     0.02 s,   102 MB
    4000 m          801x801     0.06 s,   126 MB

Flat memory instead of explosive, and faster at every size. Results are
numerically identical to the direct method (max absolute difference
6.7e-16 and 8.9e-16 at radii 20 and 50 px -- floating-point noise).

This was not a theoretical concern. `tests/data/test_density_raster.py::
test_get_building_density_reads_window_radius_from_config` sets a 2000 m
radius to check that the radius is honoured, and that test OOM-killed
the whole pytest process -- which is why the full backend suite could
not be run in one go. Both radii are env-configurable
(BUILDING_DENSITY_WINDOW_RADIUS_M, DRAINAGE_DENSITY_WINDOW_RADIUS_M), so
the same crash was reachable in production by anyone recalibrating
either value upward, not only in tests.

--- Edge behaviour is deliberately unchanged ---

`fftconvolve(..., mode="same")` treats everything outside the raster as
zero, exactly as `convolve(..., mode="constant", cval=0.0)` did. Both
callers document the consequence -- density is systematically
*underestimated* within one window radius of the AOI edge, since there
is no way to know what lies beyond it -- and that documented,
long-standing behaviour is preserved rather than quietly changed while
fixing the memory bug.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import fftconvolve


def circular_kernel(radius_px: int) -> np.ndarray:
    """A filled circle of radius `radius_px`, as a (2r+1, 2r+1) float64
    array of 1.0 inside and 0.0 outside.

    `kernel.sum()` is the window's own cell count, which callers use as
    the denominator when turning a window sum into a density.
    """
    if radius_px < 1:
        raise ValueError(f"radius_px must be >= 1, got {radius_px}")
    yy, xx = np.ogrid[-radius_px : radius_px + 1, -radius_px : radius_px + 1]
    return ((xx**2 + yy**2) <= radius_px**2).astype(np.float64)


def radius_in_pixels(radius_m: float, resolution_m: float) -> int:
    """Window radius converted to whole pixels, floored at 1 so a radius
    smaller than one cell still yields a usable 3x3 kernel rather than a
    degenerate one.
    """
    return max(1, round(radius_m / resolution_m))


def circular_window_sum(values: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Sum of `values` over `kernel`'s circular neighbourhood, per cell.

    Outside the array is treated as zero (see the module docstring on
    edge behaviour).

    Negative results are clipped to zero: FFT convolution accumulates
    floating-point error and can return values around -1e-16 where the
    true sum is exactly 0. Both callers pass non-negative inputs (a
    binary coverage mask; stream length in metres), so any negative
    output is numerical noise, and letting it through would produce
    negative densities.
    """
    out = fftconvolve(values.astype(np.float64), kernel, mode="same")
    return np.maximum(out, 0.0)
