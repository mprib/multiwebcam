"""Capture subsystem coordinator (composition root)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject

from multiwebcam.pipeline.session import CaptureSession
from multiwebcam.profiles import ControlValue, ProfileRepository, SourceProfile
from multiwebcam.sources import FrameSource, FrameSourceConfig, FrameSourceOptions, discover_frame_sources
from multiwebcam.sources.controls import set_control

logger = logging.getLogger(__name__)


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

    Owns the CaptureSession and the long-lived CapturePresenter.
    All signal/slot wiring happens here.
    """

    def __init__(self, project_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project_path = project_path
        self._repo = ProfileRepository(project_path)
        self._session: CaptureSession | None = None
        self._presenter = None  # CapturePresenter, created in initialize()
        self._sources: dict[int, SourceInfo] = {}
        self._view_connections: list[tuple] = []

    def initialize(self) -> None:
        """Discover sources, match to profiles, create session and presenter."""
        profiles = self._repo.load_all()
        profiles_by_bus = {p.bus_info: p for p in profiles}

        discovered = discover_frame_sources()

        frame_sources: list[FrameSource] = []

        for options in discovered:
            if options.bus_info in profiles_by_bus:
                profile = profiles_by_bus[options.bus_info]
            else:
                source_id = self._repo.next_source_id()
                profile = SourceProfile.with_defaults(
                    source_id=source_id,
                    bus_info=options.bus_info,
                )
                self._repo.save(profile)

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

        for profile in profiles:
            if profile.source_id not in self._sources:
                self._sources[profile.source_id] = SourceInfo(
                    source_id=profile.source_id,
                    device_path="",
                    profile=profile,
                    options=None,
                    error="Source not connected",
                )

        if frame_sources:
            self._session = CaptureSession(frame_sources)

            from multiwebcam.ui.presenters.capture import CapturePresenter
            self._presenter = CapturePresenter(
                self._session,
                self.get_source_id_lookup(),
            )

    def start(self) -> None:
        """Start the capture session."""
        if self._session:
            self._apply_saved_controls()
            self._session.start()

    def stop(self) -> None:
        """Stop presenter and session."""
        self._disconnect_view()
        if self._presenter:
            self._presenter.shutdown()
        if self._session:
            self._session.stop()

    @property
    def session(self) -> CaptureSession | None:
        return self._session

    @property
    def sources(self) -> dict[int, SourceInfo]:
        return self._sources

    def get_source_id_lookup(self) -> dict[str, int]:
        return {
            info.device_path: info.source_id
            for info in self._sources.values()
            if info.device_path and not info.error
        }

    def get_device_path(self, source_id: int) -> str | None:
        info = self._sources.get(source_id)
        return info.device_path if info and not info.error else None

    def _apply_saved_controls(self) -> None:
        for info in self._sources.values():
            if not info.device_path or info.error:
                continue
            for name, cv in info.profile.controls.items():
                set_control(info.device_path, name, cv.value)

    def _disconnect_view(self) -> None:
        """Disconnect all presenter-to-view connections before view teardown."""
        for signal, slot in self._view_connections:
            try:
                signal.disconnect(slot)
            except RuntimeError:
                pass  # Already disconnected
        self._view_connections.clear()

    def _connect(self, signal, slot) -> None:
        """Connect and track a signal-slot pair for later disconnection."""
        signal.connect(slot)
        self._view_connections.append((signal, slot))

    def create_grid_view(self, parent=None):
        """Create and wire a grid view. Returns the view only."""
        if self._session is None or self._presenter is None:
            raise RuntimeError("Cannot create grid view: no capture session")

        self._disconnect_view()

        from multiwebcam.ui.views import GridView

        view = GridView(parent)
        for source_id, info in self._sources.items():
            if info.device_path and not info.error:
                view.add_source(source_id, info.profile.label)

        p = self._presenter

        # Wire presenter -> view
        self._connect(p.frames_ready, view.display_frames)
        self._connect(p.grid_stats_updated, view.update_stats)
        self._connect(p.alignment_updated, view.update_alignment)
        self._connect(p.recording_stopping, view.set_stopping)
        self._connect(p.recording_queue_depth, view.update_queue_depth)
        self._connect(p.recording_duration, view.update_duration)

        rec_true = lambda: view.set_recording(True)
        rec_false = lambda: view.set_recording(False)
        self._connect(p.recording_started, rec_true)
        self._connect(p.recording_stopped, rec_false)

        # Wire view -> presenter (view owns these, die with view)
        output_dir = self._project_path / "recordings"
        view.record_requested.connect(lambda: p.start_recording(output_dir))
        view.stop_requested.connect(p.stop_recording)
        view.poll_interval_changed.connect(p.set_grid_poll_interval)

        p.enter_grid_mode()
        return view

    def create_focus_view(self, source_id: int, parent=None):
        """Create and wire a focus view. Returns the view only."""
        if self._session is None or self._presenter is None:
            raise RuntimeError("Cannot create focus view: no capture session")

        self._disconnect_view()

        from multiwebcam.ui.views import FocusView

        info = self._sources.get(source_id)
        if not info or info.error:
            raise ValueError(f"Source {source_id} not available")

        view = FocusView(source_id, info.profile.label, parent)
        config = FrameSourceConfig(
            resolution=info.profile.resolution,
            fps=info.profile.capture_fps,
            pixel_format=info.profile.pixel_format,
        )

        p = self._presenter

        # Wire presenter -> view
        self._connect(p.frame_ready, view.display_frame)
        self._connect(p.focus_stats_updated, view.update_stats)
        self._connect(p.resolutions_available, view.populate_resolutions)
        self._connect(p.framerates_available, view.populate_framerates)
        self._connect(p.initial_config_ready, view.set_current_config)
        self._connect(p.controls_ready, view.set_controls)
        self._connect(p.recording_stopping, view.set_stopping)

        rec_true = lambda: view.set_recording(True)
        rec_false = lambda: view.set_recording(False)
        self._connect(p.recording_started, rec_true)
        self._connect(p.recording_stopped, rec_false)

        # Wire control panel each time controls_ready fires
        def _wire_control_panel(controls) -> None:
            if view.control_panel is not None:
                view.control_panel.control_changed.connect(p.on_control_changed)
                view.control_panel.defaults_restore_requested.connect(p.on_restore_defaults)
        self._connect(p.controls_ready, _wire_control_panel)

        # Persist control changes
        persist_slot = lambda name, value: self._on_control_persist(source_id, name, value)
        self._connect(p.control_persist_requested, persist_slot)

        cleared_slot = lambda: self._on_controls_cleared(source_id)
        self._connect(p.controls_cleared, cleared_slot)

        # Wire view -> presenter (view owns these)
        view.resolution_selected.connect(p.on_resolution_selected)
        view.apply_requested.connect(lambda: self._on_apply_config(view))
        output_dir = self._project_path / "calibration" / "intrinsic"
        view.record_requested.connect(lambda: p.start_recording(output_dir))
        view.stop_requested.connect(p.stop_recording)

        p.enter_focus_mode(
            info.device_path, source_id, info.options, config,
        )
        return view

    def _on_control_persist(self, source_id: int, name: str, value: int) -> None:
        info = self._sources.get(source_id)
        if not info:
            return

        from multiwebcam.sources.controls import query_controls

        controls = query_controls(info.device_path)
        ctrl = next((c for c in controls if c.name == name), None)
        if ctrl is None:
            return

        ctrl_min = ctrl.min if ctrl.min is not None else 0
        ctrl_max = ctrl.max if ctrl.max is not None else 1
        control_value = ControlValue(
            value=value,
            min=ctrl_min,
            max=ctrl_max,
        )
        updated_profile = info.profile.with_control(name, control_value)
        self._repo.save(updated_profile)
        info.profile = updated_profile

    def _on_controls_cleared(self, source_id: int) -> None:
        info = self._sources.get(source_id)
        if not info:
            return
        updated_profile = info.profile.with_controls_cleared()
        self._repo.save(updated_profile)
        info.profile = updated_profile

    def _on_apply_config(self, view) -> None:
        """Handle Apply button -- change source configuration."""
        resolution = view.selected_resolution
        framerate = view.selected_framerate

        if resolution == (0, 0) or framerate == 0:
            self._presenter.apply_config_error("Invalid configuration selected")
            return

        new_config = FrameSourceConfig(
            resolution=resolution,
            fps=framerate,
            pixel_format="mjpeg",
        )

        device_path = self._presenter.focused_device_path

        if self._session is None:
            self._presenter.apply_config_error("No capture session active")
            return

        try:
            self._session.replace_source(device_path, new_config)
        except Exception as e:
            self._presenter.apply_config_error(str(e))
            return

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

        self._presenter.apply_config_result(new_config)
