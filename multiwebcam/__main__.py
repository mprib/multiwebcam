import sys
import os
from PySide6.QtWidgets import QApplication
from pathlib import Path

from multiwebcam.gui.main_widget import launch_main
import multiwebcam.logger

logger = multiwebcam.logger.get(__name__)


def CLI_parser():
    if len(sys.argv) == 1:
        launch_main(show_clock=False)

    if len(sys.argv) == 2:
        modifiers = sys.argv[1]

        if modifiers in ["clock", "-c"]:
            launch_main(show_clock=True)
