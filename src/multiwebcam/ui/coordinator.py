"""Capture subsystem coordinator (composition root)."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject

from multiwebcam.pipeline.session import CaptureSession
from multiwebcam.profiles import ProfileRepository, SourceProfile
from multiwebcam.sources import FrameSource, FrameSourceConfig, FrameSourceOptions, discover_frame_sources


@dataclass
class SourceInfo:
    """Runtime info for a discovered source."""

    source_id: int
    device_path: str
    profile: SourceProfile
    options: FrameSourceOptions | None
    error: str | None = None


class CaptureCoordinator(QObject):
    """Composition root for capture subsystem.

    Owns the CaptureSession and manages presenter lifecycle.
    All signal/slot wiring happens here.
    """

    def __init__(self, project_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project_path = project_path
        self._repo = ProfileRepository(project_path)
        self._session: CaptureSession | None = None
        self._sources: dict[int, SourceInfo] = {}  # source_id -> SourceInfo

    def initialize(self) -> None:
        """Discover sources, match to profiles, create session.

        Call this after construction to set up the capture pipeline.
        """
        # Load existing profiles
        profiles = self._repo.load_all()
        profiles_by_bus = {p.bus_info: p for p in profiles}

        # Discover connected sources
        discovered = discover_frame_sources()

        # Match discovered sources to profiles
        frame_sources: list[FrameSource] = []

        for options in discovered:
            if options.bus_info in profiles_by_bus:
                # Known source - use existing profile
                profile = profiles_by_bus[options.bus_info]
            else:
                # New source - create profile with defaults
                source_id = self._repo.next_source_id()
                profile = SourceProfile.with_defaults(
                    source_id=source_id,
                    bus_info=options.bus_info,
                )
                self._repo.save(profile)

            # Create FrameSource with profile settings
            config = FrameSourceConfig(
                resolution=profile.resolution,
                fps=profile.capture_fps,
                pixel_format=profile.pixel_format,
            )

            source = FrameSource(options.path, config)
            frame_sources.append(source)

            self._sources[profile.source_id] = SourceInfo(
                source_id=profile.source_id,
                device_path=options.path,
                profile=profile,
                options=options,
            )

        # Also track profiles for sources not currently connected
        for profile in profiles:
            if profile.source_id not in self._sources:
                self._sources[profile.source_id] = SourceInfo(
                    source_id=profile.source_id,
                    device_path="",  # Not connected
                    profile=profile,
                    options=None,
                    error="Source not connected",
                )

        # Create session if we have sources
        if frame_sources:
            self._session = CaptureSession(frame_sources)

    def start(self) -> None:
        """Start the capture session."""
        if self._session:
            self._session.start()

    def stop(self) -> None:
        """Stop the capture session."""
        if self._session:
            self._session.stop()

    @property
    def session(self) -> CaptureSession | None:
        """The capture session (None if no sources)."""
        return self._session

    @property
    def sources(self) -> dict[int, SourceInfo]:
        """All known sources by source_id."""
        return self._sources

    def get_source_id_lookup(self) -> dict[str, int]:
        """Get device_path -> source_id mapping for connected sources."""
        return {
            info.device_path: info.source_id
            for info in self._sources.values()
            if info.device_path and not info.error
        }

    def get_device_path(self, source_id: int) -> str | None:
        """Get device_path for a source_id, or None if not connected."""
        info = self._sources.get(source_id)
        return info.device_path if info and not info.error else None
