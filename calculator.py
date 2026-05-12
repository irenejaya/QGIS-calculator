# -*- coding: utf-8 -*-
"""Calculator plugin main class. Registers menu/toolbar action and shows dialog."""

import os

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction


class CalculatorPlugin:
    """A tiny calculator accessible from QGIS."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.menu = self.tr("&Calculator")
        self.toolbar = None
        self.dialog = None

    @staticmethod
    def tr(message):
        return QCoreApplication.translate("CalculatorPlugin", message)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.svg")
        self.action = QAction(QIcon(icon_path), self.tr("Calculator"), self.iface.mainWindow())
        self.action.setToolTip(self.tr("Open a quick calculator widget"))
        self.action.setStatusTip(self.tr("Open Calculator"))
        self.action.triggered.connect(self.run)

        self.iface.addPluginToMenu(self.menu, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu(self.menu, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

    def run(self):
        from .calculator_dialog import CalculatorDialog
        if self.dialog is None:
            self.dialog = CalculatorDialog(self.iface.mainWindow())
            self.dialog.setWindowFlag(Qt.WindowType.Window)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
