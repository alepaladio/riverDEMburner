def classFactory(iface):
    from .plugin import RiverReconditionerPlugin
    return RiverReconditionerPlugin(iface)