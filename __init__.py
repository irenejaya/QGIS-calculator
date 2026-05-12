# -*- coding: utf-8 -*-
"""Calculator QGIS plugin entry point."""


def classFactory(iface):
    from .calculator import CalculatorPlugin
    return CalculatorPlugin(iface)
