import os
import numpy as np
from osgeo import gdal

from .line_utils import get_shapely_linestring
from .interpolation import build_points_2d, resample_profile
from .feather import feather_weights
from .dem_io import sample_at_point

gdal.UseExceptions()


def burn_dem(dem_layer, line_wkt, sections, assignments,
             half_width_m, feather_width_m, allow_raise,
             burn_res, out_path, preview=False,
             points_override=None):
    """
    Read the DEM, apply the new cross-sections along the corridor,
    optionally feather, write output. Return the output path.

    Key fixes vs. v1:
      * Preserves the source DEM's rotation terms in the output geotransform.
      * If burn_res == source res, output grid is EXACTLY the source grid.
      * If burn_res differs, we produce a grid that is aligned with the
        source pixel lattice (origin snapped to source pixel corners).
    """
    import numpy as np
    from osgeo import gdal
    from shapely.geometry import Point, LineString
    from shapely.vectorized import contains as vcontains
    from scipy.interpolate import griddata

    src_ds = gdal.Open(dem_layer.source(), gdal.GA_ReadOnly)
    if src_ds is None:
        raise RuntimeError("Cannot open DEM.")
    band = src_ds.GetRasterBand(1)
    nd = band.GetNoDataValue()
    src_gt = src_ds.GetGeoTransform()
    src_crs = src_ds.GetProjection()
    src_nx = src_ds.RasterXSize
    src_ny = src_ds.RasterYSize

    src_res_x = abs(src_gt[1])   # pixel width in x
    src_res_y = abs(src_gt[5])   # pixel height in y

    # ---- Decide output grid ----
    if abs(burn_res - src_res_x) < 1e-9 and abs(burn_res - src_res_y) < 1e-9:
        # Exact source grid: reuse geotransform as-is
        out_gt = src_gt
        nx = src_nx
        ny = src_ny
    else:
        # Sub/supersample relative to source; keep source origin,
        # scale the linear part only (rotation preserved proportionally).
        sx = src_res_x / burn_res
        sy = src_res_y / burn_res
        # New geotransform: origin unchanged, linear part scaled
        out_gt = (
            src_gt[0],
            src_gt[1] / sx,
            src_gt[2] / sx,
            src_gt[3],
            src_gt[4] / sy,
            src_gt[5] / sy,
        )
        nx = int(round(src_nx * sx))
        ny = int(round(src_ny * sy))

    # ---- Build target XY grid from the output geotransform ----
    # Pixel centers: corner + (i+0.5)*dx + (j+0.5)*dy
    ii = np.arange(nx) + 0.5
    jj = np.arange(ny) + 0.5
    I, J = np.meshgrid(ii, jj)
    X = out_gt[0] + I * out_gt[1] + J * out_gt[2]
    Y = out_gt[3] + I * out_gt[4] + J * out_gt[5]

    # ---- Sample source DEM on target grid ----
    # Use GDAL's inverse geotransform per pixel so rotation is respected.
    inv_gt = gdal.InvGeoTransform(src_gt)
    if inv_gt is None:
        raise RuntimeError("Cannot invert DEM geotransform.")
    # Convert target XY back to source pixel indices
    pcol = inv_gt[0] + X * inv_gt[1] + Y * inv_gt[2]
    prow = inv_gt[3] + X * inv_gt[4] + Y * inv_gt[5]

    # Bilinear sample using array-based indexing
    src_arr = band.ReadAsArray()  # full read; ok for typical DEMs
    src_arr = src_arr.astype("float64")
    if nd is not None:
        src_arr = np.where(np.abs(src_arr - nd) < 1e-6, np.nan, src_arr)

    def _bilinear(arr, prow, pcol):
        x0 = np.floor(pcol).astype(int)
        y0 = np.floor(prow).astype(int)
        dx = pcol - x0
        dy = prow - y0
        x0c = np.clip(x0, 0, arr.shape[1] - 2)
        y0c = np.clip(y0, 0, arr.shape[0] - 2)
        v00 = arr[y0c,     x0c]
        v10 = arr[y0c,     x0c + 1]
        v01 = arr[y0c + 1, x0c]
        v11 = arr[y0c + 1, x0c + 1]
        v0 = v00 * (1 - dx) + v10 * dx
        v1 = v01 * (1 - dx) + v11 * dx
        return v0 * (1 - dy) + v1 * dy

    src_vals = _bilinear(src_arr, prow, pcol)

    # ---- Corridor mask from the buffer around the line ----
    line = get_shapely_linestring(line_wkt)
    if points_override is not None:
        # Corridor follows the override region only
        px = points_override[:, 0]
        py = points_override[:, 1]
        x_lo, x_hi = px.min(), px.max()
        y_lo, y_hi = py.min(), py.max()
        pad = feather_width_m + burn_res
        from shapely.geometry import box
        corridor = box(x_lo - pad, y_lo - pad,
                       x_hi + pad, y_hi + pad)
        mask = vcontains(corridor, X, Y)
    else:
        corridor = line.buffer(half_width_m + feather_width_m + burn_res,
                               resolution=8)
        mask = vcontains(corridor, X, Y)

    # ---- Cross-section point cloud ----
    def dem_sampler(x, y):
        # sample at (x, y) from the source array using the same inverse GT
        cc = inv_gt[0] + x * inv_gt[1] + y * inv_gt[2]
        rr = inv_gt[3] + x * inv_gt[4] + y * inv_gt[5]
        if cc < 0 or rr < 0 or cc > src_nx - 1 or rr > src_ny - 1:
            return None
        col = int(round(cc))
        row = int(round(rr))
        v = src_arr[row, col]
        return None if np.isnan(v) else float(v)

    if points_override is not None:
        points = points_override
    else:
        points, _ = build_points_2d(
            sections, assignments, line_wkt, half_width_m,
            dem_sampler, n_across=61
        )

    # ---- Interpolate point cloud onto target grid ----
    Zinterp = griddata(points[:, :2], points[:, 2], (X, Y),
                       method="linear")
    Znear = griddata(points[:, :2], points[:, 2], (X, Y),
                     method="nearest")
    Zinterp = np.where(np.isnan(Zinterp), Znear, Zinterp)

    # ---- Feather weights inside corridor ----
    w = np.zeros_like(Zinterp, dtype=float)
    if feather_width_m <= 0:
        w[mask] = 1.0
    else:
        idx = np.argwhere(mask)
        inner = max(half_width_m - feather_width_m, 0.0)
        for (j, i) in idx:
            p = Point(X[j, i], Y[j, i])
            d = line.distance(p)
            if d >= half_width_m:
                w[j, i] = 0.0
            elif d <= inner:
                w[j, i] = 1.0
            else:
                t = (half_width_m - d) / feather_width_m
                w[j, i] = t * t * (3 - 2 * t)

    # ---- Blend ----
    src_for_blend = np.where(np.isnan(src_vals), Zinterp, src_vals)
    if allow_raise:
        blended = w * Zinterp + (1.0 - w) * src_for_blend
    else:
        lowered = np.minimum(src_for_blend, Zinterp)
        blended = w * lowered + (1.0 - w) * src_for_blend

    # ---- Write ----
    if preview:
        out_path = "/vsimem/reconditioned_preview.tif"

    driver = gdal.GetDriverByName("GTiff")
    if not preview and os.path.exists(out_path):
        try:
            driver.Delete(out_path)
        except Exception:
            pass

    out_ds = driver.Create(out_path, nx, ny, 1, gdal.GDT_Float32,
                           options=["COMPRESS=LZW", "TILED=YES"])
    out_ds.SetGeoTransform(out_gt)
    out_ds.SetProjection(src_crs)
    ob = out_ds.GetRasterBand(1)
    if nd is not None:
        ob.SetNoDataValue(nd)
    ob.WriteArray(blended.astype("float32"))
    ob.FlushCache()
    out_ds = None
    return out_path