"""Camera profile dataclass for persistent configuration."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraProfile:
    """Persistent camera configuration.

    Immutable. To modify, create a new profile with changed values.

    The profile stores stable configuration (bus_info, resolution, etc.)
    but NOT ephemeral runtime state (device_path changes on reboot).
    """

    # Identity (required)
    cam_id: int  # Stable identifier, never reused
    bus_info: str  # USB topology for matching (e.g., "usb-0000:00:14.0-3.1")

    # Display (required with default)
    label: str  # User-assigned name

    # Control flags (required with default)
    ignore: bool = False  # If True, excluded from recording

    # Capture settings (required with defaults)
    resolution: tuple[int, int] = (1280, 720)
    pixel_format: str = "mjpeg"
    capture_fps: int = 30

    # V4L2 controls (optional - not all cameras support all controls)
    exposure: int | None = None
    gain: int | None = None
    white_balance: int | None = None
    focus: int | None = None

    @classmethod
    def with_defaults(cls, cam_id: int, bus_info: str, label: str | None = None) -> CameraProfile:
        """Create profile with sensible defaults.

        Args:
            cam_id: Stable identifier for this camera
            bus_info: USB topology identifier for matching
            label: Display name (defaults to 'cam_{cam_id}')
        """
        return cls(
            cam_id=cam_id,
            bus_info=bus_info,
            label=label or f"cam_{cam_id}",
        )

    def with_resolution(self, resolution: tuple[int, int]) -> CameraProfile:
        """Return new profile with updated resolution."""
        return dataclasses.replace(self, resolution=resolution)

    def with_label(self, label: str) -> CameraProfile:
        """Return new profile with updated label."""
        return dataclasses.replace(self, label=label)

    def with_ignore(self, ignore: bool) -> CameraProfile:
        """Return new profile with updated ignore flag."""
        return dataclasses.replace(self, ignore=ignore)

    def with_updates(self, **kwargs) -> CameraProfile:
        """Return new profile with updated fields."""
        return dataclasses.replace(self, **kwargs)
