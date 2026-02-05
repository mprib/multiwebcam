"""Capture subsystem coordinator (composition root)."""

from __future__ import annotations

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

    def create_grid_view(self, parent=None):
        """Create grid view and presenter, wire them together.

        Returns:
            tuple[GridView, MultiSourcePresenter]: View and its presenter
        """
        from multiwebcam.ui.presenters import MultiSourcePresenter
        from multiwebcam.ui.views import GridView

        view = GridView(parent)
        presenter = MultiSourcePresenter(
            self._session,
            self.get_source_id_lookup(),
        )

        # Add tiles for all sources
        for source_id, info in self._sources.items():
            view.add_source(source_id, info.profile.label)

        # Wire presenter signals to view
        presenter.frames_ready.connect(view.display_frames)
        presenter.stats_updated.connect(view.update_stats)
        presenter.alignment_updated.connect(view.update_alignment)
        presenter.recording_started.connect(lambda: view.set_recording(True))
        presenter.recording_stopped.connect(lambda: view.set_recording(False))

        # Wire view actions to presenter
        view.record_requested.connect(
            lambda: presenter.start_recording(self._project_path / "recordings")
        )
        view.stop_requested.connect(presenter.stop_recording)

        return view, presenter

    def create_focus_view(self, source_id: int, parent=None):
        """Create focus view and presenter for a specific source.

        Args:
            source_id: ID of source to focus on

        Returns:
            tuple[FocusView, SingleSourcePresenter]: View and its presenter.
            Caller must connect view.back_requested to their navigation logic.

        Raises:
            ValueError: If source is not available or has an error
        """
        from multiwebcam.ui.presenters import SingleSourcePresenter
        from multiwebcam.ui.views import FocusView

        info = self._sources.get(source_id)
        if not info or info.error:
            raise ValueError(f"Source {source_id} not available")

        view = FocusView(source_id, info.profile.label, parent)

        # Build current config from profile
        config = FrameSourceConfig(
            resolution=info.profile.resolution,
            fps=info.profile.capture_fps,
            pixel_format=info.profile.pixel_format,
        )

        presenter = SingleSourcePresenter(
            self._session,
            info.device_path,
            source_options=info.options,
            current_config=config,
        )

        # Wire presenter signals to view
        presenter.frame_ready.connect(view.display_frame)
        presenter.stats_updated.connect(view.update_stats)

        # Wire resolution/framerate populate signals
        presenter.resolutions_available.connect(view.populate_resolutions)
        presenter.framerates_available.connect(view.populate_framerates)

        # Wire view combo change to presenter cascade
        view.resolution_selected.connect(presenter.on_resolution_selected)

        # Wire Apply button through coordinator
        view.apply_requested.connect(
            lambda: self._on_apply_config(presenter, view)
        )

        # Set current config in view
        w, h = config.resolution
        view.set_current_config(
            resolution=f"{w}x{h}",
            framerate=str(config.fps),
        )

        return view, presenter

    def _on_apply_config(self, presenter, view) -> None:
        """Handle Apply button click - change source configuration."""
        # Read current selections from view (format always mjpeg)
        resolution = view.selected_resolution
        framerate = view.selected_framerate

        if resolution == (0, 0) or framerate == 0:
            presenter.apply_config_error("Invalid configuration selected")
            return

        new_config = FrameSourceConfig(
            resolution=resolution,
            fps=framerate,
            pixel_format="mjpeg",
        )

        device_path = presenter.device_path

        if self._session is None:
            presenter.apply_config_error("No capture session active")
            return

        try:
            self._session.replace_source(device_path, new_config)
        except Exception as e:
            presenter.apply_config_error(str(e))
            return

        # Update profile
        source_id = self.get_source_id_lookup().get(device_path)
        if source_id is not None:
            info = self._sources.get(source_id)
            if info:
                updated_profile = info.profile.with_updates(
                    resolution=resolution,
                    capture_fps=framerate,
                    pixel_format="mjpeg",
                )
                self._repo.save(updated_profile)
                info.profile = updated_profile

        # Notify presenter of success
        presenter.apply_config_result(new_config)

