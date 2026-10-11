from osgeo import gdal
from qgis.core import (
    QgsRasterLayer, QgsCoordinateReferenceSystem, QgsUnitTypes
)


from .line_utils import get_shapely_linestring
gdal.UseExceptions()


class DemError(Exception):
    pass


# ---------------------------------------------------------------------------
# Layer / dataset validation
# ---------------------------------------------------------------------------

def validate_dem_layer(dem_layer: QgsRasterLayer,
                       line_crs: QgsCoordinateReferenceSystem):
    """Raise DemError with a user-facing message on any problem."""
    if dem_layer is None or not dem_layer.isValid():
        raise DemError("DEM layer is not valid.")

    dem_crs = dem_layer.crs()
    if not dem_crs.isValid():
        raise DemError("DEM has no valid CRS.")

    if dem_crs.authid() != line_crs.authid():
        raise DemError(
            f"DEM CRS ({dem_crs.authid()}) does not match line CRS "
            f"({line_crs.authid()}). Reproject one of them first."
        )

    if dem_crs.mapUnits() != QgsUnitTypes.DistanceMeters:
        raise DemError(
            f"DEM CRS map units are {dem_crs.mapUnits()}, expected meters."
        )

    provider = dem_layer.dataProvider()
    if provider.bandCount() < 1:
        raise DemError("DEM has no raster bands.")


def open_dem_dataset(dem_layer: QgsRasterLayer) -> gdal.Dataset:
    ds = gdal.Open(dem_layer.source(), gdal.GA_ReadOnly)
    if ds is None:
        raise DemError(f"Cannot open DEM file: {dem_layer.source()}")
    if ds.RasterCount < 1:
        raise DemError("DEM file has no raster bands.")
    return ds


def check_no_data_in_bbox(ds: gdal.Dataset,
                          xmin: float, ymin: float,
                          xmax: float, ymax: float) -> bool:
    """Return True if any pixel inside bbox is NoData."""
    gt = ds.GetGeoTransform()
    inv_gt = gdal.InvGeoTransform(gt)
    if inv_gt is None:
        return False
    xoff, yoff = gdal.ApplyGeoTransform(inv_gt, xmin, ymax)
    xsz, ysz = gdal.ApplyGeoTransform(inv_gt, xmax, ymin)
    xoff, yoff = int(xoff), int(yoff)
    xsz, ysz = int(xsz) - xoff, int(ysz) - yoff
    if xsz <= 0 or ysz <= 0:
        return False

    band = ds.GetRasterBand(1)
    nd = band.GetNoDataValue()
    if nd is None:
        return False

    arr = band.ReadAsArray(xoff, yoff, xsz, ysz)
    if arr is None:
        return False

    return bool((abs(arr.astype("float64") - float(nd)) < 1e-6).any())


# ---------------------------------------------------------------------------
# Point sampling
# ---------------------------------------------------------------------------

def _pixel_center_from_xy(gt, x, y):
    inv = gdal.InvGeoTransform(gt)
    if inv is None:
        return None
    px, py = gdal.ApplyGeoTransform(inv, x, y)
    return px, py


def sample_at_point(ds: gdal.Dataset, x: float, y: float):
    """
    Bilinear sample of band 1 at (x, y). Returns None if outside or NoData.
    """
    gt = ds.GetGeoTransform()
    band = ds.GetRasterBand(1)
    nd = band.GetNoDataValue()

    pc = _pixel_center_from_xy(gt, x, y)
    if pc is None:
        return None
    px, py = pc
    if px < 0 or py < 0 or px > ds.RasterXSize - 1 or py > ds.RasterYSize - 1:
        return None

    x0 = int(px)
    y0 = int(py)
    dx = px - x0
    dy = py - y0

    x0c = min(x0, ds.RasterXSize - 2) if ds.RasterXSize > 1 else 0
    y0c = min(y0, ds.RasterYSize - 2) if ds.RasterYSize > 1 else 0
    arr = band.ReadAsArray(x0c, y0c, 2, 2)
    if arr is None or arr.size < 4:
        arr1 = band.ReadAsArray(x0, y0, 1, 1)
        if arr1 is None:
            return None
        v = float(arr1[0, 0])
        if nd is not None and abs(v - nd) < 1e-6:
            return None
        return v

    fx = dx + (x0 - x0c)
    fy = dy + (y0 - y0c)
    a = arr.astype("float64")

    if nd is not None:
        mask = abs(a - nd) < 1e-6
        if mask.any():
            # fall back to a simple nearest in the 2x2 block that isn't NoData
            for yy in range(a.shape[0]):
                for xx in range(a.shape[1]):
                    if not mask[yy, xx]:
                        return float(a[yy, xx])
            return None

    v00 = a[0, 0]; v10 = a[1, 0]; v01 = a[0, 1]; v11 = a[1, 1]
    v0 = v00 * (1 - fx) + v10 * fx
    v1 = v01 * (1 - fx) + v11 * fx
    return float(v0 * (1 - fy) + v1 * fy)


# ---------------------------------------------------------------------------
# Sampling along the line
# ---------------------------------------------------------------------------

def sample_raster_along_line(ds: gdal.Dataset,
                             line_geom_wkt: str,
                             step_m: float):
    """
    Walk along the polyline at fixed step_m using Shapely for interpolation.
    Returns a list of dicts: {chainage_m, x, y, z}.
    """
    line = get_shapely_linestring(line_geom_wkt)
    length = line.length
    if length <= 0:
        raise DemError("Line has zero length.")

    n = max(2, int(length / step_m) + 1)
    samples = []
    for i in range(n):
        d = i * step_m
        if d > length:
            break
        pt = line.interpolate(d)
        x, y = pt.x, pt.y
        z = sample_at_point(ds, x, y)
        if z is None:
            raise DemError(
                f"NoData or out-of-bounds at chainage {d:.2f} m "
                f"(x={x:.2f}, y={y:.2f})."
            )
        samples.append({"chainage_m": d, "x": x, "y": y, "z": z})

    # Ensure the true endpoint is captured
    end_pt = line.interpolate(length)
    if samples and (samples[-1]["x"] != end_pt.x or samples[-1]["y"] != end_pt.y):
        z = sample_at_point(ds, end_pt.x, end_pt.y)
        if z is None:
            raise DemError(f"NoData at line end (x={end_pt.x:.2f}, y={end_pt.y:.2f}).")
        samples.append({"chainage_m": length, "x": end_pt.x, "y": end_pt.y, "z": z})

    return samples