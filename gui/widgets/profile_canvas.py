from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class ProfileCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(9, 4), tight_layout=True)
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Chainage (m)")
        self.ax.set_ylabel("Elevation (m)")
        self.ax.grid(True, alpha=0.3)

    def plot_profile(self, chainages, elevations, title=""):
        self.ax.clear()
        self.ax.plot(chainages, elevations, "-", color="#1f77b4", lw=1.6,
                     label="DEM profile")
        self.ax.set_xlabel("Chainage (m)")
        self.ax.set_ylabel("Elevation (m)")
        self.ax.grid(True, alpha=0.3)
        if title:
            self.ax.set_title(title)
        self.draw()

    def plot_markers(self, chainages, elevations, labels=None):
        self.ax.plot(chainages, elevations, "o", color="#d62728",
                     ms=6, zorder=5)
        if labels:
            for x, y, t in zip(chainages, elevations, labels):
                self.ax.annotate(t, (x, y),
                                 textcoords="offset points",
                                 xytext=(4, 6), fontsize=8, color="#d62728")
        self.draw()