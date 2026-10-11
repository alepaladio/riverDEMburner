from osgeo import ogr
from qgis.core import QgsGeometry

import math

from shapely import wkt as shapely_wkt
from shapely.geometry import LineString

def get_shapely_linestring(wkt_or_geom):
    """
    Convert a WKT string or OGR Geometry to a single Shapely LineString.
    MultiLineStrings with more than one part are rejected unless the
    parts are already contiguous (they are concatenated in that case).
    """
    if isinstance(wkt_or_geom, str):
        geom = shapely_wkt.loads(wkt_or_geom)
    else:
        geom = shapely_wkt.loads(wkt_or_geom.ExportToWkt())

    if isinstance(geom, LineString):
        return geom

    # MultiLineString or GeometryCollection with line parts
    if hasattr(geom, "geoms"):
        parts = [g for g in geom.geoms if isinstance(g, LineString)]
        if not parts:
            raise ValueError(
                "Geometry contains no LineString parts."
            )
        if len(parts) == 1:
            return parts[0]

        # More than one part: verify the parts are contiguous
        # (end of part i == start of part i+1, within a small tolerance)
        tol = 1e-6
        for i in range(len(parts) - 1):
            end_pt = parts[i].coords[-1]
            next_start = parts[i + 1].coords[0]
            if (abs(end_pt[0] - next_start[0]) > tol or
                    abs(end_pt[1] - next_start[1]) > tol):
                raise ValueError(
                    f"The MultiLineString has {len(parts)} parts that are "
                    "not contiguous. Split it or merge it into a single "
                    "continuous LineString before running the tool."
                )

        coords = []
        for sub in parts:
            coords.extend(list(sub.coords))
        return LineString(coords)

    raise ValueError("Geometry is not a LineString or MultiLineString.")


def qgs_geom_to_ogr_wkt(geom: QgsGeometry) -> str:
    """Convert QgsGeometry to an OGR-parsable WKT (2D only)."""
    return geom.asWkt()


def line_length(geom_wkt: str) -> float:
    try:
        line = get_shapely_linestring(geom_wkt)
    except Exception:
        return 0.0
    return line.length


def point_at_chainage(geom_wkt: str, chainage: float):
    """Return (x, y) at given chainage along the polyline (WKT)."""
    try:
        line = get_shapely_linestring(geom_wkt)
    except Exception:
        return None
    L = line.length
    if chainage < 0 or chainage > L:
        return None
    pt = line.interpolate(chainage)
    return (pt.x, pt.y)


def tangent_azimuth_deg(geom_wkt: str, chainage: float, eps: float = 1.0):
    """
    Azimuth of the local tangent (0=N, 90=E), using a symmetric window
    of +/-eps metres around the requested chainage.
    """
    try:
        line = get_shapely_linestring(geom_wkt)
    except Exception:
        return 0.0
    L = line.length
    a = max(0.0, chainage - eps)
    b = min(L, chainage + eps)
    if b - a < 1e-6:
        return 0.0
    p1 = line.interpolate(a)
    p2 = line.interpolate(b)
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    return math.degrees(math.atan2(dx, dy)) % 360.0

def perpendicular_line(center_xy, azimuth_deg: float, half_width: float):
    """
    Return the two endpoints of the cross-section perpendicular to the
    local tangent: (x0, y0, x1, y1).
    """
    cx, cy = center_xy
    perp = math.radians((azimuth_deg + 90.0) % 360.0)
    ux = math.sin(perp)
    uy = math.cos(perp)
    x0 = cx - ux * half_width
    y0 = cy - uy * half_width
    x1 = cx + ux * half_width
    y1 = cy + uy * half_width
    return x0, y0, x1, y1


def ensure_line_flows_downhill(geom_wkt: str, sample_fn) -> bool:
    """
    sample_fn(chainage) -> z or None.
    Returns True if the line should be reversed (start elevation < end).
    """
    try:
        line = get_shapely_linestring(geom_wkt)
    except Exception:
        return False
    L = line.length
    z0 = sample_fn(0.0)
    z1 = sample_fn(L)
    if z0 is None or z1 is None:
        return False
    return z0 < z1


def reverse_line_wkt(geom_wkt: str) -> str:
    """Return the WKT of the same polyline reversed using Shapely."""
    try:
        line = get_shapely_linestring(geom_wkt)
    except Exception:
        return geom_wkt
    coords = list(line.coords)
    coords.reverse()
    return LineString(coords).wkt