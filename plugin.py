import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication

from .processing_provider import RiverReconditionerProvider
from .gui.setup_dialog import SetupDialog


class RiverReconditionerPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = "&River Reconditioner"
        self.provider = None
        self.setup_dialog = None

    # ---- QGIS plugin lifecycle ----
    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        action = QAction(icon, "Recondition river DEM", self.iface.mainWindow())
        action.triggered.connect(self.run_gui)
        self.iface.addToolBarIcon(action)
        self.iface.addPluginToMenu(self.menu, action)
        self.actions.append(action)

        # Register Processing provider (algorithm added in Phase 6)
        self.provider = RiverReconditionerProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        for a in self.actions:
            self.iface.removePluginMenu(self.menu, a)
            self.iface.removeToolBarIcon(a)
        self.actions.clear()
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    # ---- launch ----
    def run_gui(self):
        # Non-modal so the user can pan/zoom in QGIS while it's open
        if self.setup_dialog is None:
            self.setup_dialog = SetupDialog(self.iface)
        self.setup_dialog.refresh_layers()
        self.setup_dialog.show()
        self.setup_dialog.raise_()
        self.setup_dialog.activateWindow()