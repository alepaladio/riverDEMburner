from qgis.core import (
    QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsVectorLayer,
    QgsProject, QgsCoordinateReferenceSystem, QgsWkbTypes, QgsFields
)
from qgis.PyQt.QtCore import QVariant

from .line_utils import point_at_chainage, tangent_azimuth_deg, perpendicular_line


def compute_station_chainages(total_length_m: float, n: int):
    """Equal spacing, starting at 0, ending at L."""
    if n < 2:
        n = 2
    return [i * total_length_m / (n - 1) for i in range(n)]


def build_cross_section_lines(geom_wkt: str,
                              chainages,
                              half_width_m: float):
    """
    Returns list of dicts: {station, chainage_m, cx, cy, x0, y0, x1, y1, az}
    Perpendicular to local tangent, symmetric around center.
    """
    out = []
    for i, ch in enumerate(chainages):
        c = point_at_chainage(geom_wkt, ch)
        if c is None:
            continue
        az = tangent_azimuth_deg(geom_wkt, ch)
        x0, y0, x1, y1 = perpendicular_line(c, az, half_width_m)
        out.append({
            "station": i,
            "chainage_m": ch,
            "cx": c[0], "cy": c[1],
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "az": az,
        })
    return out


def to_memory_layer(sections, crs: QgsCoordinateReferenceSystem,
                    layer_name="River cross-sections"):
    """
    Create a QgsVectorLayer memory layer of the cross-section lines.
    Fields: station (int), chainage_m (double)
    """
    lyr = QgsVectorLayer(
        f"LineString?crs={crs.authid()}&index=yes",
        layer_name, "memory"
    )
    pr = lyr.dataProvider()
    pr.addAttributes([
        QgsField("station", QVariant.Int),
        QgsField("chainage_m", QVariant.Double),
    ])
    lyr.updateFields()

    feats = []
    for s in sections:
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromPolylineXY([
            QgsPointXY(s["x0"], s["y0"]),
            QgsPointXY(s["x1"], s["y1"]),
        ]))
        f["station"] = s["station"]
        f["chainage_m"] = s["chainage_m"]
        feats.append(f)
    pr.addFeatures(feats)
    lyr.updateExtents()
    return lyr