import logging

from aqt.qt import QDialog, QPushButton, QTextEdit, QVBoxLayout

from ..common.constants import ANKIMAPS_CONSTANTS  # ADD THIS IMPORT


class QTextEditLogHandler(logging.Handler):
    """A minimal handler that appends formatted records to a QTextEdit."""

    def __init__(self, widget: QTextEdit):
        super().__init__()
        self.widget = widget

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.widget.append(msg)
        except Exception:
            # Never let logging exceptions propagate.
            self.handleError(record)


class LogViewer(QDialog):
    """A one‑file, zero‑dependency log window."""

    def __init__(
        self, parent=None, *, level: int = logging.INFO, log_buffer: list, buffer_handler: logging.Handler
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Logs")
        self.resize(600, 400)

        layout = QVBoxLayout(self)

        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.text_edit.clear)
        layout.addWidget(clear_btn)

        self._handler = QTextEditLogHandler(self.text_edit)
        self._handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s: %(message)s"))
        self._handler.setLevel(level)

        self.addon_logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)

        if buffer_handler:
            self.addon_logger.removeHandler(buffer_handler)

        self.addon_logger.addHandler(self._handler)

        if log_buffer:
            for record in log_buffer:
                self._handler.emit(record)
            log_buffer.clear()  # Clear the buffer so it doesn't grow forever

    def closeEvent(self, event):
        self.addon_logger.removeHandler(self._handler)
        super().closeEvent(event)
