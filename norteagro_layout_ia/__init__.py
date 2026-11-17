# -*- coding: utf-8 -*-


def classFactory(iface):  # noqa: N802
    from .plugin import NorteAgroLayoutIA
    return NorteAgroLayoutIA(iface)
