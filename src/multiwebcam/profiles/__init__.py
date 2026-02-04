"""Camera profile persistence system.

Provides CameraProfile dataclass and ProfileRepository for saving/loading
camera configurations to TOML files.
"""

from multiwebcam.profiles.camera_profile import CameraProfile
from multiwebcam.profiles.repository import ProfileError, ProfileNotFoundError, ProfileParseError, ProfileRepository

__all__ = [
    "CameraProfile",
    "ProfileRepository",
    "ProfileError",
    "ProfileParseError",
    "ProfileNotFoundError",
]
