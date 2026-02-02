"""
multiwebcam - Record synchronized webcam footage.
"""

from pathlib import Path

import rtoml
from platformdirs import user_data_dir

__package_name__ = "multiwebcam"
__version__ = "0.1.2"
__author__ = "Mac Prible"
__email__ = "prible@gmail.com"
__repo_url__ = f"https://github.com/mprib/{__package_name__}/"

# Platform-appropriate application data directory
APP_DIR = Path(user_data_dir(appname=__package_name__))
APP_DIR.mkdir(exist_ok=True, parents=True)

LOG_DIR = APP_DIR / "logs"
LOG_FILE_PATH = LOG_DIR / "multiwebcam.log"

SETTINGS_PATH = APP_DIR / "settings.toml"

# User home directory
USER_DIR = Path.home()

# Load or create user settings
if SETTINGS_PATH.exists():
    USER_SETTINGS = rtoml.load(SETTINGS_PATH)
else:
    USER_SETTINGS = {
        "recent_projects": [],
        "last_project_parent": str(USER_DIR),
    }
    with open(SETTINGS_PATH, "w") as f:
        rtoml.dump(USER_SETTINGS, f)

# Reference to package root (for dev/testing)
__root__ = Path(__file__).parent.parent


def get_config(session_directory: Path) -> dict:
    """Load config.toml from a session directory."""
    config_path = session_directory / "config.toml"
    return rtoml.load(config_path)
