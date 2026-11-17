# -*- coding: utf-8 -*-
import os
import sys

_EXT_LIBS = os.path.join(os.path.dirname(__file__), "ext_libs")
if _EXT_LIBS not in sys.path:
    sys.path.insert(0, _EXT_LIBS)

def classFactory(iface):
    from .plugin import NorteAgroPlugin
    return NorteAgroPlugin(iface)
