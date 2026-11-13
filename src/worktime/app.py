import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from worktime.ui.main_window import MainWindow


def configure_app(app: QApplication) -> None:
    """Configure application-level settings and layout direction."""
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)


def main() -> int:
    """Start the application event loop and display the main window."""
    app = QApplication(sys.argv)
    configure_app(app)
    window = MainWindow()
    window.show()
    return app.exec()
