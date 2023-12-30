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


class CameraConfigTab(QDialog):
    def __init__(self, session:LiveSession, port):
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


        self.basic_frame_control = FrameControlWidget( self.session, self.port)


        logger.debug("Building FPS Control")
        self.frame_rate_spin = QSpinBox()
        self.frame_rate_spin.setValue(self.stream.fps_target)
        self.fps_display = QLabel()
        self.ignore_box = QCheckBox()

        self.place_widgets()
        self.connect_widgets()

    def toggle_advanced_controls(self):
        if self.advanced_controls_toggle.isChecked():
            self.advanced_controls.show()
        else:
            self.advanced_controls.hide()

    def connect_widgets(self):
        self.frame_rate_spin.valueChanged.connect(self.on_frame_rate_spin)
        self.frame_emitter.FPSBroadcast.connect(self.FPSUpdateSlot)
        self.frame_emitter.ImageBroadcast.connect(self.image_update)
        self.ignore_box.stateChanged.connect(self.ignore_cam)

    def place_widgets(self):
        self.setLayout(QVBoxLayout())
        self.frame_hbox = QHBoxLayout()
        self.frame_hbox.addStretch(1)
        self.frame_hbox.addWidget(self.frame_display)
        self.frame_hbox.addStretch(1)

        self.layout().addLayout(self.frame_hbox)
        self.frame_controls_layout = QVBoxLayout(self)
        self.layout().addLayout(self.frame_controls_layout)
        self.frame_controls_layout.addWidget(self.basic_frame_control)
        self.frame_controls_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.frame_controls_layout.setContentsMargins(0, 0, 0, 0)
        
        self.fps_grp = QGroupBox("FPS")
        self.fps_grp.setLayout(QHBoxLayout())
        self.fps_grp.layout().addWidget(QLabel("Target:"))
        self.fps_grp.layout().addWidget(self.frame_rate_spin)
        self.fps_grp.layout().addWidget(self.fps_display)
        self.layout().addWidget(self.fps_grp)

    def save_camera(self):
        self.session.save_camera(self.port)

    def ignore_cam(self, signal):
        if signal == 0:  # not checked
            logger.info(f"Don't ignore camera at port {self.port}")
            self.camera.ignore = False
        else:  # value of checkState() might be 2?
            logger.info(f"Ignore camera at port {self.port}")
            self.camera.ignore = True
        self.session.config.save_camera(self.camera)

    def on_frame_rate_spin(self, fps_rate):
        self.session.set_fps(fps_rate)
        logger.info(f"Changing monocalibrator frame rate for port{self.port}")

    def FPSUpdateSlot(self, fps):
        if self.stream.camera.capture.isOpened():
            # rounding to nearest integer should be close enough for our purposes
            self.fps_display.setText("Actual: " + str(round(fps, 1)))
        else:
            self.fps_display.setText("reconnecting to camera...")

    def image_update(self,qpixmap):
        self.frame_display.setPixmap(qpixmap)




class FrameControlWidget(QWidget):
    def __init__(self, session: LiveSession, port):
        super(FrameControlWidget, self).__init__()
        self.session: LiveSession = session
        self.stream: LiveStream= session.streams[port]
        self.port = port
        self.camera: Camera = self.stream.camera

        # Rotate Image
        self.cw_rotation_btn = QPushButton(
            QIcon(str(Path(__root__, "multiwebcam/gui/icons/rotate-camera-right.svg"))), ""
        )
        self.cw_rotation_btn.setMaximumSize(35, 35)
        self.ccw_rotation_btn = QPushButton(
            QIcon(str(Path(__root__, "multiwebcam/gui/icons/rotate-camera-left.svg"))), ""
        )
        self.ccw_rotation_btn.setMaximumSize(35, 35)

        # Resolution Drop Down
        # icons from https://iconoir.com
        self.resolution_combo = QComboBox()
        resolutions_text = []
        for w, h in self.stream.camera.verified_resolutions:
            resolutions_text.append(f"{int(w)} x {int(h)}")

        w, h = self.camera.size
        self.resolution_combo.setCurrentText(f"{int(w)} x {int(h)}")

        self.resolution_combo.addItems(resolutions_text)
        self.resolution_combo.setMaximumSize(100, 35)

        # Exposure slider
        self.exp_slider = QSlider(Qt.Orientation.Horizontal)
        self.exp_slider.setRange(-10, 0)
        self.exp_slider.setSliderPosition(int(self.stream.camera.exposure))
        self.exp_slider.setPageStep(1)
        self.exp_slider.setSingleStep(1)
        self.exp_slider.setMaximumWidth(200)
        self.exposure_number = QLabel()
        self.exposure_number.setText(str(int(self.stream.camera.exposure)))

        self.place_widgets()
        self.connect_widgets()

    def place_widgets(self):
        self.setLayout(QVBoxLayout())
        self.rotation_resolution_hbox = QHBoxLayout()
        self.rotation_resolution_hbox.addWidget(self.cw_rotation_btn)
        self.rotation_resolution_hbox.addWidget(self.ccw_rotation_btn)
        self.layout().addLayout(self.rotation_resolution_hbox)

        self.rotation_resolution_hbox.addWidget(self.resolution_combo)
        self.exposure_hbox = QHBoxLayout()
        self.layout().addLayout(self.exposure_hbox)

        # construct a horizontal widget with label: slider: value display
        self.exposure_label = QLabel("Exposure")
        self.exposure_label.setAlignment(Qt.AlignmentFlag.AlignRight)


        self.exposure_hbox.addWidget(self.exposure_label)
        self.exposure_hbox.addWidget(self.exp_slider)
        self.exposure_hbox.addWidget(self.exposure_number)

        self.exposure_hbox.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def connect_widgets(self):

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
        
        
        
if __name__ == "__main__":
    from multiwebcam.configurator import Configurator
    from pathlib import Path
    from PySide6.QtWidgets import QApplication
    config = Configurator(Path(r"C:\Users\Mac Prible\OneDrive\pyxy3d\webcamcap"))
    session = LiveSession(config)
    session.load_stream_tools()

    qapp = QApplication()
    cam_config_widget = CameraConfigTab(session, port=0)

    cam_config_widget.show()
    qapp.exec()