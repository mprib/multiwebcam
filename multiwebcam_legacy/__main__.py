import logging
import sys

from multiwebcam.logger import setup_logging

# Configure logging before any other imports that might log
setup_logging()

logger = logging.getLogger(__name__)

from multiwebcam.gui.main_widget import launch_main  # noqa: E402


def CLI_parser():
    if len(sys.argv) == 1:
        launch_main(show_clock=False)

    if len(sys.argv) == 2:
        modifiers = sys.argv[1]

        if modifiers in ["clock", "-c"]:
            launch_main(show_clock=True)
