import numpy as np
from scipy.interpolate import griddata


def resample_profile(profile, offsets):
    """
    profile: list of (offset_m, dz_m), may be irregularly spaced.
    offsets: 1D array of target offsets.
    Returns dz values linearly interpolated at offsets, 0 outside the profile.
    """
    if not profile:
        return np.zeros_like(offsets, dtype=float)
    p = np.asarray(profile, dtype=float)
    p = p[np.argsort(p[:, 0])]
    xs = p[:, 0]
    zs = p[:, 1]
    out = np.interp(offsets, xs, zs, left=0.0, right=0.0)
    return out


def build_points_1d(sections, assignments, line_wkt, half_width_m,
                    n_across=41):
    """
    1D mode: each station contributes its profile sampled across the
    perpendicular. Between stations we sweep the profile along the line.
    We still build a 3D point cloud (x, y, z) to interpolate over the
    corridor, but the along-line variation is linear between stations.
    """
    from .line_utils import get_shapely_linestring
    line = get_shapely_linestring(line_wkt)

    offsets = np.linspace(-half_width_m, half_width_m, n_across)

    # For each station, get (x, y, z) points
    stations = sorted(assignments.keys())
    station_data = {}   # station -> (xs, ys, datum, dz_array)

    for st in stations:
        s = next(x for x in sections if x["station"] == st)
        prof = assignments[st].get("profile")
        if not prof:
            continue

        chainage = s["chainage_m"]
        c = line.interpolate(chainage)

        # perpendicular unit vector
        eps = max(0.5, line.length / 500.0)
        a = max(0.0, chainage - eps)
        b = min(line.length, chainage + eps)
        p1 = line.interpolate(a)
        p2 = line.interpolate(b)
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        norm = (dx * dx + dy * dy) ** 0.5 or 1.0
        ux = -dy / norm
        uy = dx / norm

        # Datum = DEM elevation at the line center for this station
        # We'll pass that in later; placeholder here.
        station_data[st] = {
            "chainage": chainage,
            "center": (c.x, c.y),
            "unit": (ux, uy),
            "dz": resample_profile(prof, offsets),
        }

    return offsets, station_data


def build_points_2d(sections, assignments, line_wkt, half_width_m,
                    dem_sampler, n_across=41):
    """
    2D mode: for each station, build a perpendicular row of 3D points.
    Return as (Nx3) array: X, Y, Z.
    """
    from .line_utils import get_shapely_linestring
    line = get_shapely_linestring(line_wkt)

    offsets = np.linspace(-half_width_m, half_width_m, n_across)
    rows = []

    for st in sorted(assignments.keys()):
        s = next(x for x in sections if x["station"] == st)
        prof = assignments[st].get("profile")
        if not prof:
            continue

        chainage = s["chainage_m"]
        c = line.interpolate(chainage)

        eps = max(0.5, line.length / 500.0)
        a = max(0.0, chainage - eps)
        b = min(line.length, chainage + eps)
        p1 = line.interpolate(a)
        p2 = line.interpolate(b)
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        norm = (dx * dx + dy * dy) ** 0.5 or 1.0
        ux = -dy / norm
        uy = dx / norm

        datum = dem_sampler(c.x, c.y)
        if datum is None:
            raise RuntimeError(
                f"NoData at station {st} (chainage {chainage:.2f} m)."
            )

        dz = resample_profile(prof, offsets)
        for o, z in zip(offsets, dz):
            x = c.x + ux * o
            y = c.y + uy * o
            rows.append((x, y, datum + z))

    if not rows:
        raise RuntimeError("No valid cross-section profiles to interpolate.")
    return np.asarray(rows, dtype=float), offsets


def grid_points(points, xs_target, ys_target, method="linear"):
    """
    Interpolate scattered (x, y, z) onto the target grid.
    Falls back to 'nearest' where 'linear' fails.
    """
    X, Y = np.meshgrid(xs_target, ys_target)
    Z = griddata(points[:, :2], points[:, 2], (X, Y), method=method)
    if np.isnan(Z).any():
        Zn = griddata(points[:, :2], points[:, 2], (X, Y), method="nearest")
        Z = np.where(np.isnan(Z), Zn, Z)
    return Z

def build_linear_points(line_wkt,
                        ch_start, ch_end,
                        z_start, z_end,
                        shape_profile,
                        n_along=200):
    """
    Build a point cloud along a corridor whose bed follows a linear
    elevation ramp from (ch_start, z_start) to (ch_end, z_end).

    shape_profile: list of (offset_m, dz_m) pairs, dz relative to the
    bed elevation (0 = at bed, negative = below).
    """
    from .line_utils import get_shapely_linestring
    line = get_shapely_linestring(line_wkt)
    L = line.length

    chs = np.linspace(ch_start, ch_end, n_along)
    rows = []
    for ch in chs:
        if ch_end != ch_start:
            t = (ch - ch_start) / (ch_end - ch_start)
        else:
            t = 0.0
        bed_z = z_start + t * (z_end - z_start)

        c = line.interpolate(max(0.0, min(L, ch)))

        eps = max(0.5, L / 500.0)
        p1 = line.interpolate(max(0.0, ch - eps))
        p2 = line.interpolate(min(L, ch + eps))
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        n = (dx * dx + dy * dy) ** 0.5 or 1.0
        ux = -dy / n
        uy = dx / n

        for o, dz in shape_profile:
            x = c.x + ux * o
            y = c.y + uy * o
            z = bed_z + dz
            rows.append((x, y, z))
    return np.asarray(rows, dtype=float)