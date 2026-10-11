import os
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QMessageBox,
    QDialogButtonBox, QDoubleSpinBox, QGroupBox, QCheckBox, QFileDialog,
    QLineEdit, QWidget
)
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer, QgsFeature

from ..core.dem_io import open_dem_dataset
from ..core.shapes import sample_dem_cross_section
from .catalogue_dialog import CatalogueDialog
from .widgets.section_canvas import SectionCanvas
from ..core.shapes import SHAPES, build_catalogue_profile
from ..core.longitudinal import bed_from_stations
from ..core.interpolation import build_linear_points

MODE_AVERAGE = "Average of neighbours"
MODE_DRAW = "User-drawn"
MODE_CSV = "From CSV"
MODE_CATALOGUE = "Predefined catalogue"


class BurnDialog(QDialog):
    """
    Popup #3 – assign a mode to each cross-section AND burn the DEM.
    """

    def __init__(self, iface, line_layer, dem_layer, profile,
                 sections, section_layer, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.setWindowTitle("River Reconditioner — Burn")
        self.setModal(True)
        self.resize(1150, 720)

        self.iface = iface
        self.line_layer = line_layer
        self.dem_layer = dem_layer
        self.profile = profile
        self.sections = sections
        self.section_layer = section_layer

        self.ds = open_dem_dataset(dem_layer)

        self.assignments = {
            s["station"]: {"mode": None, "profile": None, "delta_m": 10.0}
            for s in self.sections
        }

        self._build_ui()
        self._refresh_table()

    # ---------- UI ----------
    def _build_ui(self):
        v = QVBoxLayout(self)

        top = QLabel(
            "Assign a mode to each cross-section. Click a row, then pick "
            "a mode on the right. When every station has a mode, click "
            "Burn to write the reconditioned DEM."
        )
        top.setWordWrap(True)
        v.addWidget(top)

        body = QHBoxLayout(self)
        v.addLayout(body, 1)

        self.table = QTableWidget(len(self.sections), 3, self)
        self.table.setHorizontalHeaderLabels(
            ["Station", "Chainage (m)", "Mode"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_row_changed)
        body.addWidget(self.table, 2)

        right = QVBoxLayout()
        body.addLayout(right, 1)

        gb = QGroupBox("Mode for selected station")
        right.addWidget(gb)
        gform = QFormLayout(gb)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([MODE_AVERAGE, MODE_DRAW,
                                MODE_CSV, MODE_CATALOGUE])
        gform.addRow("Mode:", self.cmb_mode)

        self.spn_delta = QDoubleSpinBox()
        self.spn_delta.setRange(0.5, 500.0)
        self.spn_delta.setValue(10.0)
        self.spn_delta.setSuffix(" m")
        gform.addRow("Δ for average:", self.spn_delta)

        self.btn_apply = QPushButton("Apply mode to selected station")
        self.btn_apply.clicked.connect(self._apply_mode_to_selected)
        right.addWidget(self.btn_apply)

        self.btn_apply_all = QPushButton("Apply same mode to all stations")
        self.btn_apply_all.clicked.connect(self._apply_mode_to_all)
        right.addWidget(self.btn_apply_all)

        self.btn_catalogue = QPushButton("Open catalogue…")
        self.btn_catalogue.clicked.connect(self._open_catalogue)
        right.addWidget(self.btn_catalogue)

        self.canvas = SectionCanvas(self)
        right.addWidget(self.canvas, 1)

        right.addStretch(0)

        # ---------- burn parameters ----------
        gb_burn = QGroupBox("Burn parameters")
        v.addWidget(gb_burn)
        bform = QFormLayout(gb_burn)

        self.cmb_interp = QComboBox()
        self.cmb_interp.addItems(["2D (griddata)", "1D along line"])
        bform.addRow("Interpolation:", self.cmb_interp)

        self.cmb_feather = QComboBox()
        self.cmb_feather.addItems(["Hard edge", "Smooth"])
        self.spn_feather = QDoubleSpinBox()
        self.spn_feather.setRange(0.0, 5000.0)
        self.spn_feather.setValue(5.0)
        self.spn_feather.setSuffix(" m")
        feather_row = QWidget()
        fr = QHBoxLayout(feather_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.addWidget(self.cmb_feather, 1)
        fr.addWidget(self.spn_feather, 1)
        bform.addRow("Feathering:", feather_row)

        self.chk_raise = QCheckBox("Allow raise (build walls)")
        bform.addRow("", self.chk_raise)

        self.spn_res = QDoubleSpinBox()
        self.spn_res.setRange(0.01, 100.0)
        px = abs(self.dem_layer.rasterUnitsPerPixelX()) or 1.0
        self.spn_res.setValue(px)
        self.spn_res.setDecimals(3)
        self.spn_res.setSuffix(" m")
        bform.addRow("Burn resolution:", self.spn_res)

        # Output
        out_row = QWidget()
        orow = QHBoxLayout(out_row)
        orow.setContentsMargins(0, 0, 0, 0)
        default_out = os.path.splitext(self.dem_layer.source())[0] + "_reconditioned.tif"
        self.edt_out = QLineEdit(default_out)
        btn_out = QPushButton("…")
        btn_out.setFixedWidth(30)
        btn_out.clicked.connect(self._pick_out)
        orow.addWidget(self.edt_out, 1)
        orow.addWidget(btn_out)
        bform.addRow("Output raster:", out_row)

        # GPKG for cross-sections
        gpkg_row = QWidget()
        grow = QHBoxLayout(gpkg_row)
        grow.setContentsMargins(0, 0, 0, 0)
        default_gpkg = os.path.splitext(default_out)[0] + "_sections.gpkg"
        self.edt_gpkg = QLineEdit(default_gpkg)
        btn_gpkg = QPushButton("…")
        btn_gpkg.setFixedWidth(30)
        btn_gpkg.clicked.connect(self._pick_gpkg)
        grow.addWidget(self.edt_gpkg, 1)
        grow.addWidget(btn_gpkg)
        bform.addRow("Cross-sections GPKG:", gpkg_row)

        self.chk_preview = QCheckBox("Preview (do not write to disk)")
        bform.addRow("", self.chk_preview)

        # ---------- Linear bed profile (optional) ----------
        self.gb_lin = QGroupBox("Linear bed profile (optional)")
        self.gb_lin.setCheckable(True)
        self.gb_lin.setChecked(False)
        v.addWidget(self.gb_lin)
        lform = QFormLayout(self.gb_lin)

        self.cmb_lin_from = QComboBox()
        self.cmb_lin_to = QComboBox()
        self._populate_anchor_dropdowns()
        lform.addRow("From station:", self.cmb_lin_from)
        lform.addRow("To station:", self.cmb_lin_to)

        self.cmb_lin_shape = QComboBox()
        for k in SHAPES.keys():
            self.cmb_lin_shape.addItem(k, k)
        lform.addRow("Shape:", self.cmb_lin_shape)

        # Sub-form for the shape's parameters (populated dynamically)
        self.lin_shape_form = QFormLayout()
        lform.addRow(self.lin_shape_form)
        self.lin_param_widgets = {}
        self.cmb_lin_shape.currentIndexChanged.connect(
            self._refresh_lin_params
        )
        self._refresh_lin_params()

        self.spn_lin_extra_depth = QDoubleSpinBox()
        self.spn_lin_extra_depth.setRange(0.0, 200.0)
        self.spn_lin_extra_depth.setValue(0.0)
        self.spn_lin_extra_depth.setSuffix(" m")
        lform.addRow("Extra depth below bed:", self.spn_lin_extra_depth)

        lbl = QLabel(
            "When enabled, stations between the anchors are cut to a "
            "straight bed line — their per-station modes are ignored."
        )
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#555;")
        lform.addRow(lbl)

        # Buttons
        bb = QDialogButtonBox()
        self.btn_burn = bb.addButton("Burn", QDialogButtonBox.AcceptRole)
        bb.addButton("Cancel", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._on_burn)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _populate_anchor_dropdowns(self):
        from ..core.dem_io import sample_at_point
        from ..core.line_utils import get_shapely_linestring
        line = get_shapely_linestring(self.profile.geom_wkt)

        self.cmb_lin_from.clear()
        self.cmb_lin_to.clear()
        for s in self.sections:
            c = line.interpolate(s["chainage_m"])
            z = sample_at_point(self.ds, c.x, c.y)
            z_str = f"{z:.2f}" if z is not None else "NoData"
            lbl = (f"Station {s['station']}  "
                   f"(ch {s['chainage_m']:.1f} m, elev {z_str} m)")
            self.cmb_lin_from.addItem(lbl, s["station"])
            self.cmb_lin_to.addItem(lbl, s["station"])
        if self.cmb_lin_to.count() >= 2:
            self.cmb_lin_to.setCurrentIndex(self.cmb_lin_to.count() - 1)

    def _refresh_lin_params(self):
        while self.lin_shape_form.count():
            item = self.lin_shape_form.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.lin_param_widgets.clear()

        name = self.cmb_lin_shape.currentData()
        if not name:
            return
        for pname, plabel, default, lo, hi in SHAPES[name]["params"]:
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(2)
            sp.setValue(default)
            sp.setSuffix(" m")
            self.lin_shape_form.addRow(plabel, sp)
            self.lin_param_widgets[pname] = sp

    # ---------- table helpers ----------
    def _current_station(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.sections[rows[0].row()]["station"]

    def _refresh_table(self):
        for r, s in enumerate(self.sections):
            st = s["station"]
            self.table.setItem(r, 0, QTableWidgetItem(str(st)))
            self.table.setItem(r, 1, QTableWidgetItem(f"{s['chainage_m']:.2f}"))
            mode = self.assignments[st]["mode"] or "—"
            self.table.setItem(r, 2, QTableWidgetItem(mode))
        self.table.resizeColumnsToContents()

    def _update_preview(self, station):
        s = next((x for x in self.sections if x["station"] == station), None)
        if s is None:
            return
        offs, elevs = sample_dem_cross_section(
            self.ds, self.profile.geom_wkt,
            s["chainage_m"], half_width_m=abs(s["x1"] - s["x0"]) / 2.0,
            n_samples=60
        )
        prof = self.assignments[station].get("profile")
        if prof:
            shape_offs = [p[0] for p in prof]
            shape_dz = [p[1] for p in prof]
        else:
            shape_offs = shape_dz = None
        self.canvas.show(offs, elevs, shape_offs, shape_dz,
                         title=f"Station {station} @ {s['chainage_m']:.2f} m")

    # ---------- signals ----------
    def _on_row_changed(self):
        st = self._current_station()
        if st is None:
            return
        cur = self.assignments[st]["mode"]
        if cur:
            idx = self.cmb_mode.findText(cur)
            if idx >= 0:
                self.cmb_mode.setCurrentIndex(idx)
        self._update_preview(st)

    # ---------- actions ----------
    def _apply_mode_to_selected(self):
        st = self._current_station()
        if st is None:
            QMessageBox.warning(self, "No selection", "Select a row first.")
            return
        mode = self.cmb_mode.currentText()
        self.assignments[st]["mode"] = mode
        self.assignments[st]["delta_m"] = self.spn_delta.value()

        if mode == MODE_CATALOGUE:
            self._open_catalogue()
        elif mode == MODE_AVERAGE:
            self._assign_average(st)

        self._refresh_table()
        self._update_preview(st)

    def _apply_mode_to_all(self):
        mode = self.cmb_mode.currentText()
        for st in self.assignments:
            self.assignments[st]["mode"] = mode
            self.assignments[st]["delta_m"] = self.spn_delta.value()
            if mode == MODE_AVERAGE:
                self._assign_average(st)
        self._refresh_table()
        st = self._current_station()
        if st is not None:
            self._update_preview(st)

    def _assign_average(self, station):
        """Sample the DEM at station ± delta along the line and average."""
        from ..core.line_utils import get_shapely_linestring
        line = get_shapely_linestring(self.profile.geom_wkt)
        s = next(x for x in self.sections if x["station"] == station)
        ch = s["chainage_m"]
        L = line.length
        d = self.assignments[station].get("delta_m", 10.0)
        a_ch = max(0.0, ch - d)
        b_ch = min(L, ch + d)

        def slice_at(chainage):
            c = line.interpolate(chainage)
            eps = max(0.5, L / 500.0)
            p1 = line.interpolate(max(0.0, chainage - eps))
            p2 = line.interpolate(min(L, chainage + eps))
            dx = p2.x - p1.x
            dy = p2.y - p1.y
            norm = (dx * dx + dy * dy) ** 0.5 or 1.0
            ux = -dy / norm
            uy = dx / norm
            hw = abs(s["x1"] - s["x0"]) / 2.0
            n = 41
            offsets = [(-hw) + 2 * hw * i / (n - 1) for i in range(n)]
            zs = []
            for o in offsets:
                from ..core.dem_io import sample_at_point
                z = sample_at_point(self.ds, c.x + ux * o, c.y + uy * o)
                zs.append(z if z is not None else 0.0)
            return offsets, zs

        offs_a, zs_a = slice_at(a_ch)
        offs_b, zs_b = slice_at(b_ch)
        zs_avg = [(za + zb) / 2.0 for za, zb in zip(zs_a, zs_b)]
        datum = zs_avg[len(zs_avg) // 2]
        profile = [(o, z - datum) for o, z in zip(offs_a, zs_avg)]
        self.assignments[station]["profile"] = profile

    def _open_catalogue(self):
        st = self._current_station()
        if st is None:
            QMessageBox.warning(self, "No selection",
                                "Select a station first.")
            return
        s = next(x for x in self.sections if x["station"] == st)
        dlg = CatalogueDialog(
            self.ds, self.profile.geom_wkt,
            s["chainage_m"], abs(s["x1"] - s["x0"]) / 2.0,
            station_label=f"Station {st}",
            parent=self
        )
        if dlg.exec_() != QDialog.Accepted or dlg.result_profile is None:
            return

        res = dlg.result_profile
        apply_all = len(res) == 4 and res[3] == "all"
        name, params, profile_pts = res[0], res[1], res[2]

        def _store(target_st):
            self.assignments[target_st]["mode"] = MODE_CATALOGUE
            self.assignments[target_st]["profile"] = profile_pts
            self.assignments[target_st]["shape"] = name
            self.assignments[target_st]["params"] = params

        if apply_all:
            for target_st in self.assignments:
                _store(target_st)
        else:
            _store(st)

        self._refresh_table()
        self._update_preview(st)

    # ---------- file pickers ----------
    def _pick_out(self):
        p, _ = QFileDialog.getSaveFileName(
            self, "Save reconditioned raster", self.edt_out.text(),
            "GeoTIFF (*.tif *.tiff)"
        )
        if p:
            self.edt_out.setText(p)

    def _pick_gpkg(self):
        p, _ = QFileDialog.getSaveFileName(
            self, "Save cross-sections", self.edt_gpkg.text(),
            "GeoPackage (*.gpkg)"
        )
        if p:
            self.edt_gpkg.setText(p)

    # ---------- burn ----------
    def _on_burn(self):
        # Validate
        linear_on = self.gb_lin.isChecked()

        # Determine which stations are covered by linear mode
        linear_range = None
        if linear_on:
            from_st = self.cmb_lin_from.currentData()
            to_st = self.cmb_lin_to.currentData()
            if from_st == to_st:
                QMessageBox.warning(
                    self, "Invalid linear bed",
                    "From and To stations must be different."
                )
                return
            lo, hi = sorted([from_st, to_st])
            linear_range = (lo, hi)

        def _station_needs_mode(st):
            if linear_range is None:
                return True
            return not (linear_range[0] <= st <= linear_range[1])

        missing = [
            st for st, a in self.assignments.items()
            if _station_needs_mode(st) and not a["mode"]
        ]
        if missing:
            QMessageBox.warning(
                self, "Incomplete",
                f"Stations without a mode: {missing}"
            )
            return

        # Ensure every station has a profile (average needs it computed)
        for st, a in self.assignments.items():
            if a["mode"] == MODE_AVERAGE and not a.get("profile"):
                self._assign_average(st)
            if a["mode"] == MODE_CATALOGUE and not a.get("profile"):
                QMessageBox.warning(
                    self, "Missing shape",
                    f"Station {st} is set to catalogue but has no shape. "
                    "Open the catalogue and apply a shape."
                )
                return
            if a["mode"] == MODE_DRAW and not a.get("profile"):
                QMessageBox.warning(
                    self, "Not implemented",
                    f"User-drawn profile for station {st} is not wired "
                    "in this build. Use catalogue, CSV, or average."
                )
                return
            if a["mode"] == MODE_CSV and not a.get("profile"):
                QMessageBox.warning(
                    self, "Not implemented",
                    f"CSV profile for station {st} is not wired "
                    "in this build. Use catalogue, average, or draw."
                )
                return

        half_width = abs(self.sections[0]["x1"] - self.sections[0]["x0"]) / 2.0
        feather_m = self.spn_feather.value() if self.cmb_feather.currentText() == "Smooth" else 0.0
        allow_raise = self.chk_raise.isChecked()
        burn_res = self.spn_res.value()
        preview = self.chk_preview.isChecked()
        out_path = self.edt_out.text()

        points_override = None
        effective_half_width = abs(
            self.sections[0]["x1"] - self.sections[0]["x0"]
        ) / 2.0

        if linear_on:
            from_st = self.cmb_lin_from.currentData()
            to_st = self.cmb_lin_to.currentData()
            try:
                bed = bed_from_stations(
                    self.ds, self.profile.geom_wkt, self.sections,
                    from_st, to_st
                )
            except Exception as e:
                QMessageBox.critical(self, "Linear bed error", str(e))
                return

            shape_name = self.cmb_lin_shape.currentData()
            shape_params = {k: w.value()
                            for k, w in self.lin_param_widgets.items()}
            profile_pts = build_catalogue_profile(shape_name, **shape_params)
            # Apply extra depth (below the bed line)
            extra = self.spn_lin_extra_depth.value()
            if extra:
                profile_pts = [(o, dz - extra) for o, dz in profile_pts]

            points_override = build_linear_points(
                self.profile.geom_wkt,
                bed.start_chainage, bed.end_chainage,
                bed.start_z, bed.end_z,
                profile_pts,
                n_along=200
            )

            # Corridor must cover the shape
            max_off = max(abs(o) for o, _ in profile_pts)
            effective_half_width = max(effective_half_width, max_off)

        from ..core.burn import burn_dem
        try:
            result_path = burn_dem(
                self.dem_layer, self.profile.geom_wkt,
                self.sections, self.assignments,
                effective_half_width, feather_m, allow_raise,
                burn_res, out_path, preview=preview,
                points_override=points_override,
            )
        except Exception as e:
            QMessageBox.critical(self, "Burn error", str(e))
            return

        # Export cross-sections to GPKG
        try:
            self._save_sections_gpkg(self.edt_gpkg.text(), half_width)
        except Exception as e:
            QMessageBox.warning(self, "GPKG warning",
                                f"Could not save cross-sections: {e}")

        # Load the result
        if preview:
            lyr = QgsRasterLayer(result_path, "Reconditioned (preview)")
        else:
            lyr = QgsRasterLayer(result_path,
                                 os.path.basename(result_path))
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
            QMessageBox.information(
                self, "Done",
                f"Output written to:\n{result_path}"
            )
        else:
            QMessageBox.warning(
                self, "Load warning",
                f"Output written but could not be loaded as a layer:\n"
                f"{result_path}"
            )
        self.accept()

    def _save_sections_gpkg(self, path, half_width):
        """Write the cross-section LineStrings to a GPKG."""
        if not path:
            return
        from qgis.core import (
            QgsVectorFileWriter, QgsFields, QgsField, QgsFeature,
            QgsGeometry, QgsPointXY, QgsWkbTypes,
            QgsCoordinateTransformContext
        )
        from qgis.PyQt.QtCore import QVariant

        crs = self.line_layer.crs()
        fields = QgsFields()
        fields.append(QgsField("station", QVariant.Int))
        fields.append(QgsField("chainage_m", QVariant.Double))
        fields.append(QgsField("shape", QVariant.String))

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.fileEncoding = "UTF-8"
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

        writer = QgsVectorFileWriter.create(
            path, fields, QgsWkbTypes.LineString, crs,
            QgsCoordinateTransformContext(), options
        )
        if writer.hasError() != QgsVectorFileWriter.NoError:
            raise RuntimeError(writer.errorMessage())

        for s in self.sections:
            f = QgsFeature(fields)
            f.setGeometry(QgsGeometry.fromPolylineXY([
                QgsPointXY(s["x0"], s["y0"]),
                QgsPointXY(s["x1"], s["y1"]),
            ]))
            f["station"] = s["station"]
            f["chainage_m"] = s["chainage_m"]
            f["shape"] = self.assignments[s["station"]].get("shape", "")
            writer.addFeature(f)
        del writer