import sys
import os
from PySide6.QtWidgets import QApplication
from pathlib import Path

from multiwebcam.gui.multicamera_widget import launch_recording_widget
from multiwebcam.gui.main_widget import launch_main
import multiwebcam.logger

logger = multiwebcam.logger.get(__name__)


def CLI_parser():
    if len(sys.argv) == 1:
        launch_main()

    if len(sys.argv) == 2:
        session_path = Path(os.getcwd())
        launch_widget = sys.argv[1]

        # if launch_widget in ["calibrate", "cal", "-c"]:
        #     launch_extrinsic_calibration_widget(session_path)

        if launch_widget in ["record", "rec", "-r"]:
            launch_recording_widget(session_path)
