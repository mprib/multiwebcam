import sys
import os
from PySide6.QtWidgets import QApplication
from pathlib import Path

from multiwebcam.gui.main_widget import launch_main
import multiwebcam.logger

logger = multiwebcam.logger.get(__name__)


def CLI_parser():
    if len(sys.argv) == 1:
        launch_main()

    if len(sys.argv) == 2:
        launch_widget = sys.argv[1]

        if launch_widget in ["record", "rec", "-r"]:
            pass
