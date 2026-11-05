from PySide6.QtWidgets import QMainWindow, QWidget

from worktime.ui import strings


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.APP_TITLE)
