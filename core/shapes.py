import math
import numpy as np
from shapely.geometry import Point
from osgeo import gdal

from .line_utils import get_shapely_linestring
from .dem_io import sample_at_point


# ---------------------------------------------------------------------------
# Catalogue shape generators
# Each returns a list of (offset_m, dz_m) pairs, offset centered at 0,
# dz negative = cut downward, dz = 0 at the outer flanks.
# ---------------------------------------------------------------------------

def rectangular(width_m: float, depth_m: float, n: int = 60):
    half = width_m / 2.0
    xs = np.linspace(-half, half, n)
    zs = np.full_like(xs, -abs(depth_m))
    return list(zip(xs.tolist(), zs.tolist()))


def triangular(width_m: float, depth_m: float, n: int = 60):
    half = width_m / 2.0
    xs = np.linspace(-half, half, n)
    # depth at center, 0 at edges, linear
    zs = -abs(depth_m) * (1.0 - np.abs(xs) / half)
    return list(zip(xs.tolist(), zs.tolist()))


def trapezoidal(top_width_m: float, bottom_width_m: float,
                depth_m: float, n: int = 60):
    top_half = top_width_m / 2.0
    bot_half = bottom_width_m / 2.0
    if bot_half > top_half:
        bot_half = top_half
    xs = np.linspace(-top_half, top_half, n)
    zs = np.zeros_like(xs)
    for i, x in enumerate(xs):
        ax = abs(x)
        if ax <= bot_half:
            zs[i] = -abs(depth_m)
        else:
            t = (ax - bot_half) / (top_half - bot_half)
            zs[i] = -abs(depth_m) * (1.0 - t)
    return list(zip(xs.tolist(), zs.tolist()))


def semicircular(width_m: float, n: int = 60):
    # Semicircle: width = diameter, depth = radius
    r = width_m / 2.0
    xs = np.linspace(-r, r, n)
    zs = -np.sqrt(np.clip(r * r - xs * xs, 0.0, None))
    return list(zip(xs.tolist(), zs.tolist()))


SHAPES = {
    "rectangular": {
        "fn": rectangular,
        "params": [
            ("width_m", "Width (m)", 20.0, 0.1, 5000.0),
            ("depth_m", "Depth (m)", 5.0, 0.01, 200.0),
        ],
    },
    "triangular": {
        "fn": triangular,
        "params": [
            ("width_m", "Width (m)", 20.0, 0.1, 5000.0),
            ("depth_m", "Depth (m)", 5.0, 0.01, 200.0),
        ],
    },
    "trapezoidal": {
        "fn": trapezoidal,
        "params": [
            ("top_width_m", "Top width (m)", 20.0, 0.1, 5000.0),
            ("bottom_width_m", "Bottom width (m)", 8.0, 0.0, 5000.0),
            ("depth_m", "Depth (m)", 5.0, 0.01, 200.0),
        ],
    },
    "semicircular": {
        "fn": semicircular,
        "params": [
            ("width_m", "Width (m)", 20.0, 0.1, 5000.0),
        ],
    },
}


def build_catalogue_profile(shape_name: str, **kwargs):
    """Return [(offset_m, dz_m), ...] for the requested shape."""
    spec = SHAPES[shape_name]
    return spec["fn"](**kwargs)


# ---------------------------------------------------------------------------
# DEM cross-section sampler (for the catalogue preview)
# ---------------------------------------------------------------------------

def sample_dem_cross_section(ds: gdal.Dataset,
                             line_wkt: str,
                             chainage_m: float,
                             half_width_m: float,
                             n_samples: int = 60):
    """
    Sample the DEM across a perpendicular to the line at chainage_m.
    Returns two lists: offsets_m (from -half to +half), elevations_m.
    """
    line = get_shapely_linestring(line_wkt)
    length = line.length
    d = max(0.0, min(chainage_m, length))

    # Local tangent via small window
    eps = max(0.5, length / 500.0)
    a = max(0.0, d - eps)
    b = min(length, d + eps)
    p1 = line.interpolate(a)
    p2 = line.interpolate(b)
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    norm = math.hypot(dx, dy) or 1.0
    # Unit perpendicular
    ux = -dy / norm
    uy = dx / norm

    c = line.interpolate(d)
    offsets = np.linspace(-half_width_m, half_width_m, n_samples)
    elevs = []
    for o in offsets:
        x = c.x + ux * o
        y = c.y + uy * o
        z = sample_at_point(ds, x, y)
        elevs.append(float(z) if z is not None else float("nan"))
    return offsets.tolist(), elevs