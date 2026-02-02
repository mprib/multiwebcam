import logging
from time import time

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QApplication,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from multiwebcam.logger import qt_handler_instance

logger = logging.getLogger(__name__)


class LogWidget(QWidget):
    def __init__(self, message: str | None = None):
        super().__init__()
        self.setWindowTitle(message or "Log")
        self._console = LogMessageViewer(self)

        self.setWindowFlags(Qt.WindowType.WindowTitleHint)

        layout = QVBoxLayout()
        layout.addWidget(self._console)

        # Verify widget working with a button to send a message
        if __name__ == "__main__":
            self._button = QPushButton(self)
            self._button.setText("Test Me")
            layout.addWidget(self._button)
            self._button.clicked.connect(test)

        self.setLayout(layout)

        # Connect to the Qt handler's signal
        qt_handler_instance.emitter.message_written.connect(self._console.appendLogMessage)


def test():
    logger.info(f"This is a test; It is {time()}")


class LogMessageViewer(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setEnabled(True)
        self.verticalScrollBar().setVisible(True)

    @Slot(str)
    def appendLogMessage(self, msg: str) -> None:
        hor_scrollbar = self.horizontalScrollBar()
        ver_scrollbar = self.verticalScrollBar()

        ver_scrollbar.setValue(ver_scrollbar.maximum())  # Scroll to bottom
        hor_scrollbar.setValue(0)  # Scroll to left
        self.insertPlainText(msg)


if __name__ == "__main__":
    from multiwebcam.logger import setup_logging

    setup_logging()

    app = QApplication([])
    dlg = LogWidget("This is only a test")
    dlg.show()
    app.exec()
