from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QSpinBox,
    QDoubleSpinBox, QDialogButtonBox, QMessageBox, QLabel
)
from qgis.core import (
    QgsProject, QgsMapLayerType, QgsRasterLayer, QgsVectorLayer,
    QgsWkbTypes, QgsUnitTypes, QgsCoordinateReferenceSystem
)

from ..core.dem_io import validate_dem_layer, open_dem_dataset, \
    check_no_data_in_bbox, DemError


class SetupDialog(QDialog):
    """Popup #1 – choose line, DEM, number of cross-sections, half-width."""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.setWindowTitle("River Reconditioner — Setup")
        self.setMinimumWidth(420)
        self._build_ui()
        self.refresh_layers()

    # ---------- UI ----------
    def _build_ui(self):
        v = QVBoxLayout(self)
        form = QFormLayout()
        v.addLayout(form)

        self.cmb_line = QComboBox()
        self.cmb_dem = QComboBox()
        self.spn_n = QSpinBox()
        self.spn_n.setRange(2, 200)
        self.spn_n.setValue(10)

        self.spn_half = QDoubleSpinBox()
        self.spn_half.setRange(1.0, 5000.0)
        self.spn_half.setDecimals(2)
        self.spn_half.setValue(25.0)
        self.spn_half.setSuffix(" m")

        form.addRow("River line layer:", self.cmb_line)
        form.addRow("DEM raster:", self.cmb_dem)
        form.addRow("Number of cross-sections:", self.spn_n)
        form.addRow("Half-width (each side):", self.spn_half)

        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color:#555;")
        v.addWidget(self.lbl_info)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        self.cmb_line.currentIndexChanged.connect(self._update_line_info)
        self.cmb_dem.currentIndexChanged.connect(self._update_dem_info)

    # ---------- population ----------
    def refresh_layers(self):
        self.cmb_line.clear()
        self.cmb_dem.clear()

        for lyr in QgsProject.instance().mapLayers().values():
            if not lyr.isValid():
                continue
            if isinstance(lyr, QgsVectorLayer) and \
               lyr.geometryType() == QgsWkbTypes.LineGeometry:
                self.cmb_line.addItem(lyr.name(), lyr.id())
            elif isinstance(lyr, QgsRasterLayer):
                self.cmb_dem.addItem(lyr.name(), lyr.id())

        self._update_line_info()
        self._update_dem_info()

    def _selected_line(self) -> QgsVectorLayer:
        lid = self.cmb_line.currentData()
        return QgsProject.instance().mapLayer(lid) if lid else None

    def _selected_dem(self) -> QgsRasterLayer:
        did = self.cmb_dem.currentData()
        return QgsProject.instance().mapLayer(did) if did else None

    # ---------- info labels ----------
    def _update_line_info(self):
        lyr = self._selected_line()
        if lyr is None:
            self.lbl_info.setText("No line layer available.")
            return
        crs = lyr.crs()
        n = lyr.featureCount()
        units = crs.mapUnits()
        meters = units == QgsUnitTypes.DistanceMeters
        msg = f"Line: {lyr.name()} | CRS {crs.authid()} | features: {n}"
        if not meters:
            msg += "  ⚠ CRS is not in meters — will be rejected on OK."
        if n != 1:
            msg += f"  ⚠ {n} features (v1 needs exactly 1)."
        self.lbl_info.setText(msg)

    def _update_dem_info(self):
        lyr = self._selected_dem()
        if lyr is None:
            return
        px = lyr.rasterUnitsPerPixelX()
        self.lbl_info.setText(
            self.lbl_info.text() + f" | DEM pixel ≈ {px:.3f} m"
        )

    # ---------- OK ----------
    def _on_ok(self):
        line = self._selected_line()
        dem = self._selected_dem()
        if line is None or dem is None:
            QMessageBox.warning(self, "Missing input",
                                "Pick both a line layer and a DEM.")
            return

        # CRS checks
        if line.crs().mapUnits() != QgsUnitTypes.DistanceMeters:
            QMessageBox.critical(
                self, "Unsupported CRS",
                "The line layer CRS is not in meters. "
                "Reproject it to a projected CRS (meters) first."
            )
            return
        if line.crs().authid() != dem.crs().authid():
            QMessageBox.critical(
                self, "CRS mismatch",
                f"Line CRS {line.crs().authid()} ≠ DEM CRS "
                f"{dem.crs().authid()}."
            )
            return

        # Exactly one feature
        if line.featureCount() != 1:
            QMessageBox.critical(
                self, "Multiple features",
                f"The line layer must contain exactly 1 feature, "
                f"found {line.featureCount()}. Split/select first."
            )
            return

        # DEM validity + NoData
        try:
            validate_dem_layer(dem, line.crs())
            ds = open_dem_dataset(dem)
        except DemError as e:
            QMessageBox.critical(self, "DEM error", str(e))
            return

        feat = next(line.getFeatures())
        geom = feat.geometry()
        bb = geom.boundingBox()
        try:
            if check_no_data_in_bbox(ds,
                                     bb.xMinimum(), bb.yMinimum(),
                                     bb.xMaximum(), bb.yMaximum()):
                QMessageBox.critical(
                    self, "NoData in DEM",
                    "The DEM contains NoData pixels inside the line "
                    "bounding box. Aborting."
                )
                return
        finally:
            ds = None  # close dataset

        # --- Hand off to Phase 2 (profile dialog) ---
        n = self.spn_n.value()
        half = self.spn_half.value()
        self._launch_profile(line, dem, n, half)

    def _launch_profile(self, line, dem, n, half):
        # Imported here so Phase 1 still works if Phase 2 file not yet present
        try:
            from .profile_dialog import ProfileDialog
        except ImportError:
            QMessageBox.information(
                self, "Phase 1 complete",
                f"Setup OK.\n\nLine: {line.name()}\nDEM: {dem.name()}\n"
                f"N sections: {n}\nHalf-width: {half} m\n\n"
                "Profile Dialog will be added in Phase 2."
            )
            self.accept()
            return

        dlg = ProfileDialog(self.iface, line, dem, n, half, parent=self)
        dlg.exec_()