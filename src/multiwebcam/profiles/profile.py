"""Source profile dataclass for persistent configuration."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ControlValue:
    """A V4L2 control setting with its constraints."""

    value: int
    min: int
    max: int

    def __post_init__(self) -> None:
        if self.min > self.max:
            raise ValueError(f"min ({self.min}) cannot be greater than max ({self.max})")
        if not (self.min <= self.value <= self.max):
            raise ValueError(
                f"value ({self.value}) must be between min ({self.min}) and max ({self.max})"
            )


@dataclass(frozen=True, slots=True)
class SourceProfile:
    """Persistent source configuration.

    Immutable. To modify, create a new profile with changed values.

    The profile stores stable configuration (bus_info, resolution, etc.)
    but NOT ephemeral runtime state (device_path changes on reboot).

    Note: source_id maps 1:1 to Caliscope's camera_id. Output files use
    cam_N.mp4 naming for Caliscope compatibility.
    """

    # Identity (required)
    source_id: int  # Stable identifier, never reused. Maps to Caliscope's camera_id.
    bus_info: str  # USB topology for matching (e.g., "usb-0000:00:14.0-3.1")

    # Display (required with default)
    label: str  # User-assigned name

    # Control flags (required with default)
    ignore: bool = False  # If True, excluded from recording

    # Capture settings (required with defaults)
    resolution: tuple[int, int] = (1280, 720)
    pixel_format: str = "mjpeg"
    capture_fps: int = 30

    # V4L2 controls (optional - flexible dict of control_name: ControlValue)
    controls: dict[str, ControlValue] = field(default_factory=dict)

    @classmethod
    def with_defaults(cls, source_id: int, bus_info: str, label: str | None = None) -> SourceProfile:
        """Create profile with sensible defaults.

        Args:
            source_id: Stable identifier for this source. Maps to Caliscope's camera_id.
            bus_info: USB topology identifier for matching
            label: Display name (defaults to 'source_{source_id}')
        """
        return cls(
            source_id=source_id,
            bus_info=bus_info,
            label=label or f"source_{source_id}",
        )

    def with_resolution(self, resolution: tuple[int, int]) -> SourceProfile:
        """Return new profile with updated resolution."""
        return dataclasses.replace(self, resolution=resolution)

    def with_label(self, label: str) -> SourceProfile:
        """Return new profile with updated label."""
        return dataclasses.replace(self, label=label)

    def with_ignore(self, ignore: bool) -> SourceProfile:
        """Return new profile with updated ignore flag."""
        return dataclasses.replace(self, ignore=ignore)

    def with_updates(self, **kwargs) -> SourceProfile:
        """Return new profile with updated fields."""
        return dataclasses.replace(self, **kwargs)

    def with_control(self, name: str, control: ControlValue) -> SourceProfile:
        """Return new profile with added/updated control."""
        new_controls = {**self.controls, name: control}
        return dataclasses.replace(self, controls=new_controls)
