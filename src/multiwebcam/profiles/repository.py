"""Profile repository for loading and saving camera profiles to TOML."""

from __future__ import annotations

import logging
from pathlib import Path

import rtoml

from multiwebcam.profiles.camera_profile import CameraProfile

logger = logging.getLogger(__name__)


class ProfileError(Exception):
    """Base exception for profile operations."""


class ProfileParseError(ProfileError):
    """TOML file exists but is malformed."""


class ProfileNotFoundError(ProfileError):
    """Requested profile doesn't exist."""


class ProfileRepository:
    """Load and save camera profiles to TOML.

    Operates on a single file: <project_path>/multiwebcam.toml
    Uses rtoml for fast, correct TOML serialization.

    Not thread-safe by design - expected to be used from main thread only.
    """

    def __init__(self, project_path: Path) -> None:
        """Initialize repository.

        Args:
            project_path: Directory containing multiwebcam.toml
        """
        self._project_path = project_path
        self._toml_path = project_path / "multiwebcam.toml"

    def load_all(self) -> list[CameraProfile]:
        """Load all profiles from TOML.

        Returns empty list if file doesn't exist (fresh project).

        Raises:
            ProfileParseError: If file exists but is malformed or missing required fields.
        """
        if not self._toml_path.exists():
            logger.debug(f"No TOML file at {self._toml_path}, returning empty list")
            return []

        try:
            data = rtoml.load(self._toml_path)
        except Exception as e:
            raise ProfileParseError(f"Failed to parse TOML file: {e}") from e

        # Extract cameras array
        cameras_list = data.get("cameras", [])
        if not isinstance(cameras_list, list):
            raise ProfileParseError("'cameras' must be an array of tables")

        profiles = []
        for i, camera_dict in enumerate(cameras_list):
            try:
                profile = self._dict_to_profile(camera_dict)
                profiles.append(profile)
            except (TypeError, KeyError) as e:
                raise ProfileParseError(f"Invalid camera entry at index {i}: {e}") from e

        logger.info(f"Loaded {len(profiles)} profile(s) from {self._toml_path}")
        return profiles

    def save(self, profile: CameraProfile) -> None:
        """Save or update a profile.

        If a profile with the same cam_id exists, it's replaced.
        If not, the profile is appended.
        Creates the TOML file if it doesn't exist.

        Args:
            profile: Profile to save
        """
        # Load existing profiles
        profiles = self.load_all()

        # Replace or append
        found = False
        for i, existing in enumerate(profiles):
            if existing.cam_id == profile.cam_id:
                profiles[i] = profile
                found = True
                break

        if not found:
            profiles.append(profile)

        # Write back
        self._write_all(profiles)
        logger.debug(f"Saved profile cam_id={profile.cam_id} to {self._toml_path}")

    def delete(self, cam_id: int) -> bool:
        """Delete a profile by cam_id.

        Args:
            cam_id: Camera ID to delete

        Returns:
            True if deleted, False if not found.
        """
        profiles = self.load_all()
        original_count = len(profiles)
        profiles = [p for p in profiles if p.cam_id != cam_id]

        if len(profiles) < original_count:
            self._write_all(profiles)
            logger.debug(f"Deleted profile cam_id={cam_id}")
            return True

        return False

    def get_by_bus_info(self, bus_info: str) -> CameraProfile | None:
        """Find profile matching the given bus_info.

        Args:
            bus_info: USB topology identifier

        Returns:
            Matching profile or None if not found.
        """
        profiles = self.load_all()
        for profile in profiles:
            if profile.bus_info == bus_info:
                return profile
        return None

    def get_by_cam_id(self, cam_id: int) -> CameraProfile | None:
        """Find profile by cam_id.

        Args:
            cam_id: Camera ID

        Returns:
            Matching profile or None if not found.
        """
        profiles = self.load_all()
        for profile in profiles:
            if profile.cam_id == cam_id:
                return profile
        return None

    def next_cam_id(self) -> int:
        """Return next available cam_id.

        Returns:
            max(existing_cam_ids) + 1, or 0 if no profiles exist.
        """
        profiles = self.load_all()
        if not profiles:
            return 0
        return max(p.cam_id for p in profiles) + 1

    def _write_all(self, profiles: list[CameraProfile]) -> None:
        """Write all profiles to TOML file.

        Args:
            profiles: List of profiles to write
        """
        # Build TOML structure
        data = {
            "cameras": [self._profile_to_dict(p) for p in profiles],
        }

        # Ensure directory exists
        self._project_path.mkdir(parents=True, exist_ok=True)

        # Write to file
        rtoml.dump(data, self._toml_path)

    def _profile_to_dict(self, profile: CameraProfile) -> dict:
        """Convert profile to dict for TOML serialization.

        Omits V4L2 controls that are None.
        """
        d = {
            "cam_id": profile.cam_id,
            "label": profile.label,
            "bus_info": profile.bus_info,
            "ignore": profile.ignore,
            "resolution": list(profile.resolution),  # TOML wants list, not tuple
            "pixel_format": profile.pixel_format,
            "capture_fps": profile.capture_fps,
        }

        # Add V4L2 controls only if not None
        if profile.exposure is not None:
            d["exposure"] = profile.exposure
        if profile.gain is not None:
            d["gain"] = profile.gain
        if profile.white_balance is not None:
            d["white_balance"] = profile.white_balance
        if profile.focus is not None:
            d["focus"] = profile.focus

        return d

    def _dict_to_profile(self, d: dict) -> CameraProfile:
        """Convert dict from TOML to CameraProfile.

        Unknown fields are ignored for forward compatibility.

        Raises:
            KeyError: If required field is missing
            TypeError: If field has wrong type
        """
        # Required fields
        cam_id = d["cam_id"]
        label = d["label"]
        bus_info = d["bus_info"]

        # Fields with defaults
        ignore = d.get("ignore", False)
        resolution_list = d.get("resolution", [1280, 720])
        resolution = tuple(resolution_list)  # Convert list back to tuple
        pixel_format = d.get("pixel_format", "mjpeg")
        capture_fps = d.get("capture_fps", 30)

        # Optional V4L2 controls
        exposure = d.get("exposure")
        gain = d.get("gain")
        white_balance = d.get("white_balance")
        focus = d.get("focus")

        return CameraProfile(
            cam_id=cam_id,
            label=label,
            bus_info=bus_info,
            ignore=ignore,
            resolution=resolution,
            pixel_format=pixel_format,
            capture_fps=capture_fps,
            exposure=exposure,
            gain=gain,
            white_balance=white_balance,
            focus=focus,
        )
