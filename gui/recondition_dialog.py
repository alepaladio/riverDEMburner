import os
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QDoubleSpinBox,
    QCheckBox, QLineEdit, QPushButton, QHBoxLayout, QWidget,
    QLabel, QDialogButtonBox, QMessageBox, QFileDialog
)
from qgis.core import QgsProject, QgsRasterLayer

from ..core.dem_io import open_dem_dataset, sample_at_point
from ..core.line_utils import get_shapely_linestring
from ..core.longitudinal import bed_from_stations
from ..core.interpolation import build_linear_points
from ..core.shapes import rectangular
from ..core.burn import burn_dem


class ReconditionDialog(QDialog):
    """
    Recondition a DEM by cutting a straight line between two anchor
    stations. No per-station mode assignment: only the anchors and a
    single width/extra-depth are needed.
    """

    def __init__(self, iface, line_layer, dem_layer, profile, sections,
                 parent=None):
        super().__init__(parent or iface.mainWindow())
        self.setWindowTitle("River Reconditioner — Remove lump")
        self.setModal(True)
        self.resize(700, 520)

        self.iface = iface
        self.line_layer = line_layer
        self.dem_layer = dem_layer
        self.profile = profile
        self.sections = sections

        self.ds = open_dem_dataset(dem_layer)

        self._build_ui()
        self._populate_anchor_dropdowns()

    # ---------- UI ----------
    def _build_ui(self):
        v = QVBoxLayout(self)

        intro = QLabel(
            "Cut a straight bed line between two anchor stations. "
            "Everything between the anchors is replaced with this line "
            "(plus any extra depth you specify). Outside this range the "
            "DEM is untouched."
        )
        intro.setWordWrap(True)
        v.addWidget(intro)

        form = QFormLayout()
        v.addLayout(form)

        self.cmb_from = QComboBox()
        self.cmb_to = QComboBox()
        form.addRow("From station:", self.cmb_from)
        form.addRow("To station:", self.cmb_to)

        self.spn_width = QDoubleSpinBox()
        self.spn_width.setRange(0.5, 5000.0)
        self.spn_width.setValue(25.0)
        self.spn_width.setSuffix(" m")
        form.addRow("Width of corridor:", self.spn_width)

        self.spn_extra = QDoubleSpinBox()
        self.spn_extra.setRange(0.0, 200.0)
        self.spn_extra.setValue(0.0)
        self.spn_extra.setDecimals(2)
        self.spn_extra.setSuffix(" m")
        form.addRow("Extra depth below bed:", self.spn_extra)

        self.chk_raise = QCheckBox("Allow raise (build walls)")
        self.chk_raise.setChecked(False)
        form.addRow("", self.chk_raise)

        self.cmb_feather = QComboBox()
        self.cmb_feather.addItems(["Hard edge", "Smooth"])
        self.spn_feather = QDoubleSpinBox()
        self.spn_feather.setRange(0.0, 5000.0)
        self.spn_feather.setValue(5.0)
        self.spn_feather.setSuffix(" m")
        fr = QWidget()
        fl = QHBoxLayout(fr)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(self.cmb_feather, 1)
        fl.addWidget(self.spn_feather, 1)
        form.addRow("Feathering:", fr)

        self.spn_res = QDoubleSpinBox()
        self.spn_res.setRange(0.01, 100.0)
        px = abs(self.dem_layer.rasterUnitsPerPixelX()) or 1.0
        self.spn_res.setValue(px)
        self.spn_res.setDecimals(3)
        self.spn_res.setSuffix(" m")
        form.addRow("Burn resolution:", self.spn_res)

        # Output
        out_row = QWidget()
        ol = QHBoxLayout(out_row)
        ol.setContentsMargins(0, 0, 0, 0)
        default_out = os.path.splitext(
            self.dem_layer.source())[0] + "_reconditioned.tif"
        self.edt_out = QLineEdit(default_out)
        btn_out = QPushButton("…")
        btn_out.setFixedWidth(30)
        btn_out.clicked.connect(self._pick_out)
        ol.addWidget(self.edt_out, 1)
        ol.addWidget(btn_out)
        form.addRow("Output raster:", out_row)

        self.chk_preview = QCheckBox("Preview (do not write to disk)")
        form.addRow("", self.chk_preview)

        bb = QDialogButtonBox()
        bb.addButton("Burn", QDialogButtonBox.AcceptRole).clicked.connect(
            self._on_burn)
        bb.addButton("Cancel", QDialogButtonBox.RejectRole).clicked.connect(
            self.reject)
        v.addWidget(bb)

    # ---------- Anchors ----------
    def _populate_anchor_dropdowns(self):
        line = get_shapely_linestring(self.profile.geom_wkt)
        for s in self.sections:
            c = line.interpolate(s["chainage_m"])
            z = sample_at_point(self.ds, c.x, c.y)
            z_str = f"{z:.2f}" if z is not None else "NoData"
            label = (f"Station {s['station']}  "
                     f"(ch {s['chainage_m']:.1f} m, elev {z_str} m)")
            self.cmb_from.addItem(label, s["station"])
            self.cmb_to.addItem(label, s["station"])
        if self.cmb_to.count() >= 2:
            self.cmb_to.setCurrentIndex(self.cmb_to.count() - 1)

    # ---------- File picker ----------
    def _pick_out(self):
        p, _ = QFileDialog.getSaveFileName(
            self, "Save reconditioned raster", self.edt_out.text(),
            "GeoTIFF (*.tif *.tiff)"
        )
        if p:
            self.edt_out.setText(p)

    # ---------- Burn ----------
    def _on_burn(self):
        from_st = self.cmb_from.currentData()
        to_st = self.cmb_to.currentData()
        if from_st == to_st:
            QMessageBox.warning(self, "Invalid anchors",
                                "From and To must differ.")
            return

        try:
            bed = bed_from_stations(
                self.ds, self.profile.geom_wkt, self.sections,
                from_st, to_st
            )
        except Exception as e:
            QMessageBox.critical(self, "Anchor error", str(e))
            return

        # Shape: rectangular, width = user width, depth = user extra
        half_w = self.spn_width.value() / 2.0
        extra = self.spn_extra.value()
        shape_pts = rectangular(width_m=half_w * 2.0,
                                depth_m=extra, n=60)

        try:
            points_override = build_linear_points(
                self.profile.geom_wkt,
                bed.start_chainage, bed.end_chainage,
                bed.start_z, bed.end_z,
                shape_pts,
                n_along=200
            )
        except Exception as e:
            QMessageBox.critical(self, "Build error", str(e))
            return

        feather_m = (self.spn_feather.value()
                     if self.cmb_feather.currentText() == "Smooth" else 0.0)

        # Corridor half-width must cover the shape
        effective_half = half_w

        try:
            result_path = burn_dem(
                self.dem_layer, self.profile.geom_wkt,
                self.sections, {},   # no per-station assignments
                effective_half, feather_m,
                self.chk_raise.isChecked(),
                self.spn_res.value(),
                self.edt_out.text(),
                preview=self.chk_preview.isChecked(),
                points_override=points_override,
            )
        except Exception as e:
            QMessageBox.critical(self, "Burn error", str(e))
            return

        # Load result
        lyr = QgsRasterLayer(
            result_path,
            "Reconditioned (preview)" if self.chk_preview.isChecked()
            else os.path.basename(result_path)
        )
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
        QMessageBox.information(self, "Done", f"Output: {result_path}")
        self.accept()