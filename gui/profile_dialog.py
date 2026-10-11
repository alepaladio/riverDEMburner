from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QDialogButtonBox, QMessageBox
)
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

from ..core.dem_io import open_dem_dataset
from ..core.profile import build_profile
from ..core.sections import (
    compute_station_chainages, build_cross_section_lines, to_memory_layer
)
from .widgets.profile_canvas import ProfileCanvas


class ProfileDialog(QDialog):
    """
    Popup #2 – show the DEM longitudinal profile and the N perpendicular
    cross-sections, then continue to the burn dialog (Phase 3).
    """

    def __init__(self, iface, line_layer: QgsVectorLayer,
                 dem_layer: QgsRasterLayer, n_sections: int,
                 half_width: float, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.setWindowTitle("River Reconditioner — Profile")
        self.setModal(True)          # safety first
        self.resize(1000, 620)

        self.iface = iface
        self.line_layer = line_layer
        self.dem_layer = dem_layer
        self.n_sections = n_sections
        self.half_width = half_width

        self.section_layer = None
        self.profile = None
        self.sections = []

        self._build_ui()
        self._run()

    # ---------- UI ----------
    def _build_ui(self):
        v = QVBoxLayout(self)

        self.lbl = QLabel("Sampling DEM along line…")
        v.addWidget(self.lbl)

        self.canvas = ProfileCanvas(self)
        v.addWidget(self.canvas, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        bb = QDialogButtonBox()

        self.btn_recond = bb.addButton(
            "Recondition (remove lump)", QDialogButtonBox.ActionRole
        )
        self.btn_channel = bb.addButton(
            "Burn channel…", QDialogButtonBox.ActionRole
        )
        bb.addButton("Cancel", QDialogButtonBox.RejectRole)

        self.btn_recond.clicked.connect(self._on_recondition)
        self.btn_channel.clicked.connect(self._on_channel)
        bb.rejected.connect(self._on_cancel)

        row.addWidget(bb)
        v.addLayout(row)

    def _on_cancel(self):
        # remove the temporary cross-section layer before closing
        if self.section_layer is not None:
            QgsProject.instance().removeMapLayer(self.section_layer.id())
            self.section_layer = None
        self.reject()

    # ---------- processing ----------
    def _run(self):
        # DEM open
        try:
            self.ds = open_dem_dataset(self.dem_layer)
        except Exception as e:
            QMessageBox.critical(self, "DEM error", str(e))
            self.reject()
            return

        # Pick the single feature (validated in Setup)
        feats = list(self.line_layer.getFeatures())
        if len(feats) != 1:
            QMessageBox.critical(self, "Line error",
                                 "Expected exactly 1 line feature.")
            self.reject()
            return
        geom = feats[0].geometry()

        # Step: target ~200 samples per profile, no finer than 0.5 m
        length_m = geom.length()
        if length_m <= 0:
            QMessageBox.critical(self, "Line error", "Line has zero length.")
            self.reject()
            return
        step = max(0.5, length_m / 200.0)

        try:
            self.profile = build_profile(self.ds, geom, step)
        except Exception as e:
            QMessageBox.critical(self, "Profile error", str(e))
            self.reject()
            return

        # Build cross-sections
        chainages = compute_station_chainages(self.profile.length_m,
                                              self.n_sections)
        self.sections = build_cross_section_lines(
            self.profile.geom_wkt, chainages, self.half_width
        )
        if not self.sections:
            QMessageBox.critical(self, "Sections error",
                                 "Could not build cross-sections.")
            self.reject()
            return

        # Push memory layer
        crs = self.line_layer.crs()
        self.section_layer = to_memory_layer(self.sections, crs)
        QgsProject.instance().addMapLayer(self.section_layer)

        # Plot
        cs = self.profile.chainages()
        es = self.profile.elevations()
        title = (f"{self.line_layer.name()}  •  {self.dem_layer.name()}"
                 f"  •  reversed={self.profile.reversed}"
                 f"  •  {self.n_sections} sections @ ±{self.half_width:g} m")
        self.canvas.plot_profile(cs, es, title=title)

        # Markers: interpolate DEM elevation at each station chainage
        import numpy as np
        cs_arr = np.array(cs)
        es_arr = np.array(es)
        marker_z = [float(np.interp(s["chainage_m"], cs_arr, es_arr))
                    for s in self.sections]
        self.canvas.plot_markers(
            [s["chainage_m"] for s in self.sections], marker_z,
            labels=[str(s["station"]) for s in self.sections]
        )

        self.lbl.setText(
            f"Line length: {self.profile.length_m:.2f} m  •  "
            f"{len(self.sections)} cross-sections placed  •  "
            f"temporary layer added to map."
        )

    # ---------- actions ----------
    def _on_recondition(self):
        try:
            from .recondition_dialog import ReconditionDialog
        except ImportError as e:
            QMessageBox.critical(self, "Missing module",
                                 f"recondition_dialog.py not found: {e}")
            return
        dlg = ReconditionDialog(
            self.iface,
            line_layer=self.line_layer,
            dem_layer=self.dem_layer,
            profile=self.profile,
            sections=self.sections,
            parent=self
        )
        dlg.exec_()

    def _on_channel(self):
        try:
            from .burn_dialog import BurnDialog
        except ImportError as e:
            QMessageBox.critical(self, "Missing module",
                                 f"burn_dialog.py not found: {e}")
            return
        dlg = BurnDialog(
            self.iface,
            line_layer=self.line_layer,
            dem_layer=self.dem_layer,
            profile=self.profile,
            sections=self.sections,
            section_layer=self.section_layer,
            parent=self
        )
        dlg.exec_()