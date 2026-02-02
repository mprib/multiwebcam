"""
Logging configuration for multiwebcam.

Provides rotating file handler, console output, and Qt signal integration.
Call setup_logging() once at application startup before any other imports.
"""

import logging
import logging.handlers
import os
import sys

from PySide6 import QtCore

from multiwebcam import LOG_DIR, LOG_FILE_PATH


class StderrLogger:
    """
    A file-like object that redirects writes to a logger.
    """

    def __init__(self, logger_name: str = "stderr"):
        self.logger = logging.getLogger(logger_name)

    def write(self, message: str) -> None:
        if message.strip():
            self.logger.error(message.strip())

    def flush(self) -> None:
        pass


def handle_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback,
) -> None:
    """
    Global exception hook to log unhandled exceptions.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))


class LogEmitter(QtCore.QObject):
    """
    A QObject that holds the signal for QtHandler.
    Uses composition to avoid method name clashes with logging.Handler.
    """

    message_written = QtCore.Signal(str)


class QtHandler(logging.Handler):
    """
    A logging handler that emits log records via a Qt signal.
    Uses LogEmitter instance (composition) to integrate with Qt GUI.
    """

    def __init__(self) -> None:
        super().__init__()
        self.emitter = LogEmitter()

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        if message:
            self.emitter.message_written.emit(message + "\n")


# Global instance accessible to GUI components (e.g., LogWidget)
qt_handler_instance = QtHandler()


def setup_logging() -> None:
    """
    Configure the root logger for the entire application.

    Sets up three handlers:
    1. RotatingFileHandler - persists logs to disk (5MB max, 5 backups)
    2. StreamHandler - console output for immediate feedback
    3. QtHandler - emits signals for GUI log display (disabled in DEBUG mode)

    Also redirects stderr and installs a global exception hook.
    """
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        return

    root_logger.setLevel(logging.INFO)
    log_format = "%(asctime)s | %(levelname)-8s | %(name)-15s | %(lineno)4d | %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    # 1. File Handler - rotating to prevent unbounded growth
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        filename=LOG_FILE_PATH,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)

    # 2. Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    # 3. Qt Handler - skip during debugging to avoid stepping through signal emissions
    if os.getenv("DEBUG") != "1":
        qt_handler_instance.setLevel(logging.INFO)
        qt_format = "%(name)s: %(message)s"
        qt_formatter = logging.Formatter(qt_format)
        qt_handler_instance.setFormatter(qt_formatter)
        root_logger.addHandler(qt_handler_instance)

    # Redirect stderr and set up exception hook
    sys.stderr = StderrLogger()  # type: ignore[assignment]
    sys.excepthook = handle_exception

    root_logger.info("Logging configured.")
