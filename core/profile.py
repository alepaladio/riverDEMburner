from qgis.core import QgsGeometry

from .dem_io import sample_raster_along_line
from .line_utils import (
    qgs_geom_to_ogr_wkt, ensure_line_flows_downhill, reverse_line_wkt,
    line_length
)


class ProfileResult:
    def __init__(self, geom_wkt, samples, reversed_):
        self.geom_wkt = geom_wkt            # final (possibly reversed)
        self.samples = samples              # list of dicts
        self.reversed = reversed_           # bool
        self.length_m = line_length(geom_wkt)

    def elevations(self):
        return [s["z"] for s in self.samples]

    def chainages(self):
        return [s["chainage_m"] for s in self.samples]


def build_profile(ds, line_geom: QgsGeometry, step_m: float) -> ProfileResult:
    """
    - Convert QgsGeometry → OGR WKT
    - Reverse if needed so start is higher than end
    - Sample the DEM along the line at step_m
    """
    wkt = qgs_geom_to_ogr_wkt(line_geom)

    def z_at(chainage):
        # tiny helper that uses the sample function; here we sample the DEM
        from .dem_io import sample_at_point
        from .line_utils import point_at_chainage
        pt = point_at_chainage(wkt, chainage)
        if pt is None:
            return None
        return sample_at_point(ds, pt[0], pt[1])

    should_reverse = ensure_line_flows_downhill(wkt, z_at)
    if should_reverse:
        wkt = reverse_line_wkt(wkt)

    samples = sample_raster_along_line(ds, wkt, step_m)
    return ProfileResult(wkt, samples, should_reverse)