from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class SectionCanvas(FigureCanvasQTAgg):
    """
    Canvas for a single cross-section:
    X = offset from centerline (m), Y = elevation (m or dz from datum).
    Can display:
      - the DEM terrain slice (solid),
      - a proposed shape (dashed),
      - a filled area between them for emphasis.
    """

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(6, 4), tight_layout=True)
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        self._style()

    def _style(self):
        self.ax.set_xlabel("Offset from centerline (m)")
        self.ax.set_ylabel("Elevation (m)")
        self.ax.grid(True, alpha=0.3)
        self.ax.axvline(0, color="#888", lw=0.8, ls=":")

    def show(self, offsets_terrain, elevs_terrain,
             offsets_shape=None, dz_shape=None,
             title=""):
        self.ax.clear()
        self._style()

        if offsets_terrain is not None and elevs_terrain is not None:
            self.ax.plot(offsets_terrain, elevs_terrain,
                         "-", color="#1f77b4", lw=1.6, label="DEM terrain")

            if offsets_shape is not None and dz_shape is not None:
                # Datum = DEM elevation at offset 0
                try:
                    idx0 = offsets_terrain.index(0.0)
                except ValueError:
                    idx0 = min(range(len(offsets_terrain)),
                               key=lambda i: abs(offsets_terrain[i]))
                datum = elevs_terrain[idx0]
                target = [datum + dz for dz in dz_shape]
                self.ax.plot(offsets_shape, target,
                             "--", color="#d62728", lw=1.6,
                             label="Proposed")
                self.ax.fill_between(offsets_shape, target,
                                     [datum] * len(target),
                                     color="#d62728", alpha=0.15)

        if title:
            self.ax.set_title(title)
        self.ax.legend(loc="best", fontsize=8)
        self.draw()