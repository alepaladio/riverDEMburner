from qgis.core import QgsProcessingProvider


class RiverReconditionerProvider(QgsProcessingProvider):
    def id(self):
        return "river_reconditioner"

    def name(self):
        return "River Reconditioner"

    def longName(self):
        return self.name()

    def loadAlgorithms(self):
        # Phase 6: self.addAlgorithm(RiverReconditionerAlgorithm())
        pass