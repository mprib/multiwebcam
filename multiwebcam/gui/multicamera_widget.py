from time import sleep
import math
from pathlib import Path
from threading import Thread
from enum import Enum

from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QWidget,
    QSpinBox,
    QLineEdit,
    QScrollArea,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from multiwebcam.session.session import LiveSession
from multiwebcam.cameras.synchronizer import Synchronizer
import multiwebcam.logger

logger = multiwebcam.logger.get(__name__)
# Whatever the target frame rate, the GUI will only display a portion of the actual frames
# this is done to cut down on computational overhead.
RENDERED_FPS = 6


class NextRecordingActions(Enum):
    StartRecording = "Start Recording"
    StopRecording = "Stop Recording"
    AwaitSave = "--Saving Frames--"


class MultiCameraWidget(QWidget):
    def __init__(self, session: LiveSession, parent=None):
        super(MultiCameraWidget, self).__init__(parent)
        self.session = session
        self.synchronizer: Synchronizer = self.session.synchronizer
        self.ports = self.synchronizer.ports


        # create tools to build and emit the displayed frame
        self.thumbnail_emitter = self.session.multicam_frame_emitter

        self.frame_rate_spin = QSpinBox()
        self.frame_rate_spin.setValue(self.session.fps_target)
        self.frame_rate_spin.setMaximumWidth(50)
   
        self.render_rate_spin = QSpinBox()
        self.render_rate_spin.setValue(self.session.multicam_render_fps) 
        self.render_rate_spin.setMaximumWidth(50)

        self.next_action = NextRecordingActions.StartRecording
        self.start_stop = QPushButton(self.next_action.value)
        self.destination_label = QLabel("Recording Destination:")
        self.recording_directory = QLineEdit(self.get_next_recording_directory())

        self.dropped_fps_label = QLabel()

        # all video output routed to qlabels stored in a dictionariy
        # make it as square as you can get it
        self.recording_displays = {str(port): QLabel() for port in self.ports}
        # self.recording_frame_display = QLabel()

        self.place_widgets()
        self.connect_widgets()

        # commenting this out for now...just let people record whenever.
        # self.update_btn_eligibility()

        logger.info("Recording widget init complete")

    def update_btn_eligibility(self):
        if self.session.is_recording_eligible():
            self.start_stop.setEnabled(True)
            logger.info("Record button eligibility updated: Eligible")
        else:
            self.start_stop.setEnabled(False)
            logger.info("Record button eligibility updated: Not Eligible")

    def get_next_recording_directory(self):
        folders = [item.name for item in self.session.path.iterdir() if item.is_dir()]
        recording_folders = [
            folder for folder in folders if folder.startswith("recording_")
        ]
        recording_counts = [folder.split("_")[1] for folder in recording_folders]
        recording_counts = [
            int(rec_count) for rec_count in recording_counts if rec_count.isnumeric()
        ]

        if len(recording_counts) == 0:
            next_directory = "recording_1"

        else:
            next_directory = "recording_" + str(max(recording_counts) + 1)

        return next_directory

    def place_widgets(self):
        self.setLayout(QVBoxLayout())
        self.settings_group = QGroupBox("Settings")
        self.settings_layout = QHBoxLayout()
        self.settings_group.setLayout(self.settings_layout)

        # Frame Rate layout
        frame_rate_layout = QHBoxLayout()
        frame_rate_layout.addWidget(QLabel("Target Frame Rate:"), alignment=Qt.AlignmentFlag.AlignRight)
        frame_rate_layout.addWidget(self.frame_rate_spin, alignment=Qt.AlignmentFlag.AlignLeft)
        self.settings_layout.addLayout(frame_rate_layout)

        # Rendered Rate layout
        rendered_rate_layout = QHBoxLayout()
        rendered_rate_label = QLabel("Rendered Rate:")
        rendered_rate_label.setToolTip("Manages the rate the GUI refreshes. Reduce this to free up system resources for recording at Target FPS.")
        rendered_rate_layout.addWidget(rendered_rate_label, alignment=Qt.AlignmentFlag.AlignRight)
        rendered_rate_layout.addWidget(self.render_rate_spin, alignment=Qt.AlignmentFlag.AlignLeft)
        self.settings_layout.addLayout(rendered_rate_layout)

        self.layout().addWidget(self.settings_group)

        self.record_controls = QGroupBox()
        self.record_controls.setLayout(QHBoxLayout())
        self.record_controls.layout().addWidget(self.start_stop)
        self.record_controls.layout().addWidget(self.destination_label)
        self.record_controls.layout().addWidget(self.recording_directory)

        self.layout().addWidget(self.record_controls)

        dropped_fps_layout = QHBoxLayout()
        dropped_fps_layout.addStretch(1)
        dropped_fps_layout.addWidget(self.dropped_fps_label)
        dropped_fps_layout.addStretch(1)
        self.layout().addLayout(dropped_fps_layout)

        camera_count = len(self.ports)
        grid_columns = int(math.ceil(camera_count**0.5))

        frame_grid = QGridLayout()
        row = 0
        column = 0
        for port in sorted(self.ports):
            frame_grid.addWidget(self.recording_displays[str(port)], row, column)
            # update row and column for next iteration
            if column >= grid_columns - 1:
                # start fresh on next row
                column = 0
                row += 1
            else:
                column += 1

        frame_display_layout = QHBoxLayout()
        frame_display_layout.addStretch(1)
        frame_display_layout.addLayout(frame_grid)
        frame_display_layout.addStretch(1)
        
        scroll_view = QWidget()
        scroll_view.setLayout(frame_display_layout)        
        self.scroll_area = QScrollArea()
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(scroll_view)
        
        self.layout().addWidget(self.scroll_area)
        # self.layout().addLayout(frame_display_layout)

    def connect_widgets(self):
        self.thumbnail_emitter.ThumbnailImagesBroadcast.connect(self.ImageUpdateSlot)
        self.frame_rate_spin.valueChanged.connect(self.session.set_fps)
        self.render_rate_spin.valueChanged.connect(self.session.set_multicam_render_fps)
        self.thumbnail_emitter.dropped_fps.connect(self.update_dropped_fps)
        self.start_stop.clicked.connect(self.toggle_start_stop)
        self.session.fps_target_updated.connect(self.update_fps_target)
        self.session.multi_recording_complete_signal.connect(
            self.on_recording_complete
        )

    def toggle_start_stop(self):
        logger.info(
            f"Start/Stop Recording Toggled... Current state: {self.next_action}"
        )

        if self.next_action == NextRecordingActions.StartRecording:
            self.next_action = NextRecordingActions.StopRecording
            self.start_stop.setText(self.next_action.value)
            self.recording_directory.setEnabled(False)

            logger.info("Initiate recording")
            recording_path: Path = Path(
                self.session.path, self.recording_directory.text()
            )
            self.session.start_synchronized_recording(recording_path)

        elif self.next_action == NextRecordingActions.StopRecording:
            # need to wait for session to signal that recording is complete
            self.next_action = NextRecordingActions.AwaitSave
            self.start_stop.setEnabled(False)
            self.start_stop.setText(self.next_action.value)
            logger.info("Stop recording and initiate final save of file")
            thread = Thread(target=self.session.stop_synchronized_recording, args=[], daemon=True)
            thread.start()
            # self.session.stop_recording()

        elif self.next_action == NextRecordingActions.AwaitSave:
            logger.info("Recording button toggled while awaiting save")

    def on_recording_complete(self):
        logger.info(
            "Recording complete signal received...updating next action and button"
        )
        self.next_action = NextRecordingActions.StartRecording
        self.start_stop.setText(self.next_action.value)
        logger.info("Enabling start/stop recording button")
        self.start_stop.setEnabled(True)
        logger.info("Successfully enabled start/stop recording button")
        next_recording = self.get_next_recording_directory()
        self.recording_directory.setEnabled(True)
        self.recording_directory.setText(next_recording)
        logger.info(
            f"Successfully reset text and renamed recording directory to {next_recording}"
        )
        # pass

    def update_fps_target(self):
        self.frame_rate_spin.setValue(self.session.fps_target)

    @Slot(dict)
    def update_dropped_fps(self, dropped_fps: dict):
        "Unravel dropped fps dictionary to a more readable string"
        text = "Rate of Frame Dropping by Port:    "
        for port, drop_rate in dropped_fps.items():
            text += f"{port}: {drop_rate:.0%}        "
        self.dropped_fps_label.setText(text)

    @Slot(dict)
    def ImageUpdateSlot(self, q_image_dict: dict):
        logger.debug("About to get qpixmap from qimage")
        for port, thumbnail in q_image_dict.items():
            qpixmap = QPixmap.fromImage(thumbnail)
            logger.debug("About to set qpixmap to display")
            self.recording_displays[port].setPixmap(qpixmap)
            logger.debug("successfully set display")

