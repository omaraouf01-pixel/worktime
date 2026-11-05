from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

import worktime
from worktime.app import configure_app
from worktime.ui import strings
from worktime.ui.main_window import MainWindow


def test_package_version() -> None:
    assert worktime.__version__ == "0.1.0"


def test_main_window_smoke(qapp: QApplication, qtbot: QtBot) -> None:
    configure_app(qapp)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == strings.APP_TITLE
    assert qapp.layoutDirection() == Qt.LayoutDirection.RightToLeft
