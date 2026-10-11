from .dem_io import sample_at_point
from .line_utils import get_shapely_linestring


class LinearBed:
    """A straight-line bed profile between two (chainage, elevation) anchors."""

    def __init__(self, start_chainage, start_z, end_chainage, end_z):
        self.start_chainage = float(start_chainage)
        self.start_z = float(start_z)
        self.end_chainage = float(end_chainage)
        self.end_z = float(end_z)

    def z_at(self, chainage):
        if chainage < self.start_chainage or chainage > self.end_chainage:
            return None
        t = (chainage - self.start_chainage) / \
            (self.end_chainage - self.start_chainage)
        return self.start_z + t * (self.end_z - self.start_z)


def bed_from_stations(dem_ds, line_wkt, sections,
                      from_station, to_station):
    """
    Build a LinearBed from the DEM elevation at the centerline of two
    anchor stations. Returns (bed, from_chainage, to_chainage).
    """
    line = get_shapely_linestring(line_wkt)
    s_from = next(s for s in sections if s["station"] == from_station)
    s_to = next(s for s in sections if s["station"] == to_station)

    c1 = line.interpolate(s_from["chainage_m"])
    c2 = line.interpolate(s_to["chainage_m"])
    z1 = sample_at_point(dem_ds, c1.x, c1.y)
    z2 = sample_at_point(dem_ds, c2.x, c2.y)
    if z1 is None or z2 is None:
        raise RuntimeError(
            "NoData at anchor station centerline; cannot define linear bed."
        )
    return LinearBed(s_from["chainage_m"], z1,
                     s_to["chainage_m"], z2)