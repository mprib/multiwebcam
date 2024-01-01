import multiwebcam.logger

from pathlib import Path
from threading import Thread

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QSpinBox,
    QComboBox,
    QGridLayout,
    QCheckBox,
    QDialog,
    QGroupBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

# Append main repo to top of path to allow import of backend
from multiwebcam.gui.frame_emitter import FrameEmitter
from multiwebcam.cameras.camera import Camera
from multiwebcam.cameras.live_stream import LiveStream
from multiwebcam.session.session import LiveSession
from multiwebcam import __root__

logger = multiwebcam.logger.get(__name__)


class CameraConfigTab(QWidget):
    def __init__(self, session: LiveSession, port):
        super(CameraConfigTab, self).__init__()

        # set up variables for ease of reference
        self.session = session
        self.port = port
        self.stream = self.session.streams[port]
        self.camera = self.stream.camera

        # need frame emitter to create actual frames and track FPS/grid count
        App = QApplication.instance()
        DISPLAY_WIDTH = App.primaryScreen().size().width()
        DISPLAY_HEIGHT = App.primaryScreen().size().height()

        self.pixmap_edge = min(DISPLAY_WIDTH / 3, DISPLAY_HEIGHT / 3)
        self.frame_emitter = self.session.frame_emitters[self.port]
        self.frame_display = QLabel()

        self.setWindowTitle("Camera Configuration and Calibration")
        self.setContentsMargins(0, 0, 0, 0)

        ################# Basic Controls
        # Rotate Image
        self.cw_rotation_btn = QPushButton(
            QIcon(str(Path(__root__, "multiwebcam/gui/icons/rotate-camera-right.svg"))),
            "",
        )
        self.cw_rotation_btn.setMaximumSize(35, 35)
        self.ccw_rotation_btn = QPushButton(
            QIcon(str(Path(__root__, "multiwebcam/gui/icons/rotate-camera-left.svg"))),
            "",
        )
        self.ccw_rotation_btn.setMaximumSize(35, 35)

        # Resolution Drop Down
        # icons from https://iconoir.com
        self.resolution_combo = QComboBox()
        resolutions_text = []
        for w, h in self.stream.camera.verified_resolutions:
            resolutions_text.append(f"{int(w)} x {int(h)}")

        w, h = self.camera.size
        self.resolution_combo.addItems(resolutions_text)
        self.resolution_combo.setCurrentText(f"{int(w)} x {int(h)}")
        self.resolution_combo.setMaximumSize(100, 35)

        # Exposure slider
        # self.exposure_label = QLabel("Exposure")
        self.exp_slider = QSlider(Qt.Orientation.Horizontal)
        self.exp_slider.setRange(-10, 0)
        self.exp_slider.setSliderPosition(int(self.stream.camera.exposure))
        self.exp_slider.setPageStep(1)
        self.exp_slider.setSingleStep(1)
        self.exp_slider.setMaximumWidth(200)
        self.exposure_number = QLabel()
        self.exposure_number.setMaximumWidth(35)
        self.exposure_number.setText(str(int(self.stream.camera.exposure)))

        self.record_btn = QPushButton("Record")
        self.record_btn.setMaximumSize(100, 40)

        logger.debug("Building FPS Control")
        self.frame_rate_spin = QSpinBox()
        self.frame_rate_spin.setMaximumWidth(35)

        self.update_fps_target()
        self.fps_display = QLabel()
        
        self.place_widgets()
        self.connect_widgets()

    def update_fps_target(self):
        self.frame_rate_spin.setValue(self.session.fps_target)

    def connect_widgets(self):
        self.frame_rate_spin.valueChanged.connect(self.on_frame_rate_spin)
        self.frame_emitter.FPSBroadcast.connect(self.FPSUpdateSlot)
        self.frame_emitter.ImageBroadcast.connect(self.image_update)
        # self.ignore_checkbox.stateChanged.connect(self.update_ignore)
        self.session.fps_target_updated.connect(self.update_fps_target)
        # Counter Clockwise rotation called because the display image is flipped
        self.cw_rotation_btn.clicked.connect(self.stream.camera.rotate_CCW)
        self.cw_rotation_btn.clicked.connect(self.save_camera)

        # Clockwise rotation called because the display image is flipped
        self.ccw_rotation_btn.clicked.connect(self.stream.camera.rotate_CW)
        self.ccw_rotation_btn.clicked.connect(self.save_camera)

        # resolution combo box
        self.resolution_combo.currentTextChanged.connect(self.change_resolution)

        # exposure slider
        self.exp_slider.valueChanged.connect(self.update_exposure)
        # self.ignore_box.stateChanged.connect(self.ignore_cam)
        self.record_btn.clicked.connect(self.start_stop_record)
        self.session.single_recording_complete.connect(self.enable_recording)
    

    def place_widgets(self):
        grid_layout = QGridLayout()  # Create a new QGridLayout

        # Adding frame_display with stretch on either side

        grid_layout.addWidget(self.frame_display, 0,1,1,2) # span 1 row and 2 columns
        grid_layout.setColumnStretch(0, 1)  # Left stretch
        grid_layout.setColumnStretch(3, 1)  # Right stretch

        # Adding rotation and resolution buttons
        frame_controls = QHBoxLayout()
        frame_controls.addWidget(self.cw_rotation_btn)
        frame_controls.addWidget(self.ccw_rotation_btn)
        frame_controls.addWidget(self.resolution_combo)
        grid_layout.addLayout(frame_controls,1,1, 1,2)

        # Adding exposure widgets
        exposure_controls = QGroupBox("Exposure")
        # exposure_controls.addWidget(self.exposure_label)
        exposure_layout = QHBoxLayout()
        exposure_controls.setLayout(exposure_layout)
        exposure_layout.addWidget(self.exp_slider)
        exposure_layout.addWidget(self.exposure_number)
        exposure_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(exposure_controls, 2, 1)

        # Adding FPS group
        fps_grp = QGroupBox("FPS")
        fps_hbox_layout = QHBoxLayout()
        fps_grp.setLayout(fps_hbox_layout)
        fps_hbox_layout.addWidget(QLabel("Target:"))
        fps_hbox_layout.addWidget(self.frame_rate_spin)
        fps_hbox_layout.addWidget(self.fps_display)

        grid_layout.addWidget(fps_grp, 2, 2)  
        grid_layout.addWidget(self.record_btn, 3, 1)  # Positioned at the center

        self.setLayout(grid_layout)  # Set the layout to the grid layout

    def on_frame_rate_spin(self, fps_rate):
        self.session.set_fps(fps_rate)
        logger.info(f"Changing stream frame rate for port{self.port}")

    def FPSUpdateSlot(self, fps):
        if self.stream.camera.capture.isOpened():
            # rounding to nearest integer should be close enough for our purposes
            self.fps_display.setText("Actual: " + str(round(fps, 1)))
        else:
            self.fps_display.setText("reconnecting to camera...")

    def image_update(self, qpixmap):
        self.frame_display.setPixmap(qpixmap)

    def enable_recording(self):
        self.record_btn.setText("Record")
        self.record_btn.setEnabled(True)
        self.interface_enabled(True)

    def start_stop_record(self):
        if self.record_btn.text() == "Record":
            self.record_btn.setText("Stop")
            self.session.start_single_stream_recording(self.port)
            self.interface_enabled(False)
        elif self.record_btn.text() == "Stop":
            self.record_btn.setText("--Saving--")
            self.record_btn.setEnabled(False)
            self.session.stop_single_stream_recording()


    def interface_enabled(self, enabled:bool):
        self.exp_slider.setEnabled(enabled)
        self.ccw_rotation_btn.setEnabled(enabled)
        self.cw_rotation_btn.setEnabled(enabled)
        self.frame_rate_spin.setEnabled(enabled)
        self.resolution_combo.setEnabled(enabled)
         
    
    def save_camera(self):
        # normally wouldn't bother with a one-liner function, but it makes connecting
        # to the signal more straightforward
        self.session.config.save_camera(self.camera)

    def update_exposure(self, exp):
        self.stream.camera.exposure = exp
        self.exposure_number.setText(str(exp))
        self.save_camera()

    def change_resolution(self, res_text):
        # call the cam_cap widget to change the resolution, but do it in a
        # thread so that it doesn't halt your progress

        w, h = res_text.split("x")
        w, h = int(w), int(h)
        new_res = (w, h)
        logger.info(f"Attempting to change resolution of camera at port {self.port}")

        def change_res_worker(new_res):
            self.stream.change_resolution(new_res)

            # clear out now irrelevant params
            self.camera.matrix = None
            self.camera.distortions = None
            self.camera.error = None
            self.camera.grid_count = None
            self.save_camera()

        self.change_res_thread = Thread(
            target=change_res_worker,
            args=(new_res,),
            daemon=True,
        )
        self.change_res_thread.start()


##############################################################################################################################


if __name__ == "__main__":
    from multiwebcam.configurator import Configurator
    from pathlib import Path
    from PySide6.QtWidgets import QApplication
    from multiwebcam.session.session import SessionMode

    config = Configurator(Path(r"C:\Users\Mac Prible\OneDrive\pyxy3d\webcamcap"))
    session = LiveSession(config)
    session.load_stream_tools()
    session.set_mode(SessionMode.SingleCamera)
    session.set_active_single_stream(0)

    qapp = QApplication()
    cam_config_widget = CameraConfigTab(session, port=0)

    cam_config_widget.show()
    qapp.exec()
