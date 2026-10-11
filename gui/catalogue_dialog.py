from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QDoubleSpinBox, QPushButton, QLabel, QDialogButtonBox, QGroupBox
)

from ..core.shapes import (
    SHAPES, build_catalogue_profile, sample_dem_cross_section
)
from .widgets.section_canvas import SectionCanvas


class CatalogueDialog(QDialog):
    """
    Popup #4 – choose one of the catalogue cross-section shapes,
    preview it over the DEM slice at the current station.
    Returns via self.result_profile: (shape_name, params, profile list)
    or None if cancelled.
    """

    def __init__(self, dem_ds, line_wkt, chainage_m, half_width_m,
                 station_label="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Cross-section catalogue — {station_label}")
        self.setModal(True)
        self.resize(1000, 500)

        self.dem_ds = dem_ds
        self.line_wkt = line_wkt
        self.chainage_m = chainage_m
        self.half_width_m = half_width_m

        self.result_profile = None

        self._build_ui()
        self._refresh_params()
        self._refresh_preview()

    # ---------- UI ----------
    def _build_ui(self):
        h = QHBoxLayout(self)

        # Left: canvas
        left = QVBoxLayout()
        self.canvas = SectionCanvas(self)
        left.addWidget(self.canvas, 1)
        h.addLayout(left, 2)

        # Right: controls
        right = QVBoxLayout()
        h.addLayout(right, 1)

        gb_shape = QGroupBox("Shape")
        right.addWidget(gb_shape)
        v = QVBoxLayout(gb_shape)

        self.cmb_shape = QComboBox()
        for k in SHAPES.keys():
            self.cmb_shape.addItem(k, k)
        v.addWidget(self.cmb_shape)

        self.form = QFormLayout()
        v.addLayout(self.form)

        self.param_widgets = {}  # name -> QDoubleSpinBox

        gb_actions = QGroupBox("Apply")
        right.addWidget(gb_actions)
        va = QVBoxLayout(gb_actions)
        self.btn_this = QPushButton("Apply to this station")
        self.btn_all = QPushButton("Apply to all stations")
        va.addWidget(self.btn_this)
        va.addWidget(self.btn_all)

        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color:#555;")
        right.addWidget(self.lbl_info)

        right.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)

        # Signals
        self.cmb_shape.currentIndexChanged.connect(self._refresh_params)
        self.btn_this.clicked.connect(self._apply_this)
        self.btn_all.clicked.connect(self._apply_all)

    # ---------- Params ----------
    def _refresh_params(self):
        # Clear old form
        while self.form.count():
            item = self.form.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.param_widgets.clear()

        name = self.cmb_shape.currentData()
        spec = SHAPES[name]
        for pname, plabel, default, lo, hi in spec["params"]:
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(2)
            sp.setValue(default)
            sp.setSuffix(" m")
            sp.valueChanged.connect(self._refresh_preview)
            self.form.addRow(plabel, sp)
            self.param_widgets[pname] = sp

        self._refresh_preview()

    # ---------- Preview ----------
    def _params(self):
        return {k: w.value() for k, w in self.param_widgets.items()}

    def _refresh_preview(self):
        name = self.cmb_shape.currentData()
        try:
            profile = build_catalogue_profile(name, **self._params())
        except Exception as e:
            self.lbl_info.setText(f"Shape error: {e}")
            return

        # Sample DEM
        try:
            offs, elevs = sample_dem_cross_section(
                self.dem_ds, self.line_wkt,
                self.chainage_m, self.half_width_m, n_samples=60
            )
        except Exception as e:
            offs, elevs = [], []
            self.lbl_info.setText(f"DEM sample error: {e}")

        shape_offs = [p[0] for p in profile]
        shape_dz = [p[1] for p in profile]

        self.canvas.show(offs, elevs, shape_offs, shape_dz,
                         title=f"{name} — chainage {self.chainage_m:.2f} m")
        self.lbl_info.setText(
            f"{name}: " + ", ".join(f"{k}={v:.2f}" for k, v in self._params().items())
        )

    # ---------- Actions ----------
    def _apply_this(self):
        name = self.cmb_shape.currentData()
        profile = build_catalogue_profile(name, **self._params())
        self.result_profile = (name, self._params(), profile)
        self.accept()

    def _apply_all(self):
        # Same as _apply_this, but the caller decides scope.
        # We flag it via a marker attribute.
        self._apply_this()
        self.result_profile = self.result_profile + ("all",)  # (name, params, profile, "all")