
import multiwebcam.logger

from datetime import datetime
from pathlib import Path
from time import sleep
from threading import Event
from queue import Queue

import cv2
from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QFont, QIcon, QImage, QPixmap
from multiwebcam.cameras.live_stream import LiveStream

logger = multiwebcam.logger.get(__name__)

class FrameEmitter(QThread):
    # establish signals from the frame that will be displayed in real time
    # within the GUI
    ImageBroadcast = Signal(QPixmap)
    FPSBroadcast = Signal(float)

    def __init__(self, stream:LiveStream, pixmap_edge_length=None):
        # pixmap_edge length is from the display window. Keep the display area
        # square to keep life simple.
        super(FrameEmitter, self).__init__()
        self.stream = stream
        self.in_q = Queue(1)

        logger.info(f"Frame emitter at port {self.stream.port} subscribing to stream")
        self.pixmap_edge_length = pixmap_edge_length
        self.rotation_count = stream.camera.rotation_count
        self.undistort = False
        self.keep_collecting = Event()
        self.start()

    def subscribe(self):
        self.stream.subscribe(self.in_q)
            
    def unsubscribe(self):
        self.stream.unsubscribe(self.in_q)

    def run(self):
        self.keep_collecting.set()

        while self.keep_collecting.is_set():
            # Grab a frame from the queue and broadcast to displays
            self.frame_packet  = self.in_q.get()
            self.frame = self.frame_packet.frame

            self.frame = resize_to_square(self.frame)
            self.apply_rotation()

            image = self.cv2_to_qlabel(self.frame)
            pixmap = QPixmap.fromImage(image)

            if self.pixmap_edge_length:
                pixmap = pixmap.scaled(
                    int(self.pixmap_edge_length),
                    int(self.pixmap_edge_length),
                    Qt.AspectRatioMode.KeepAspectRatio,
                )
            self.ImageBroadcast.emit(pixmap)
            
            # moved to monocalibrator...delete if works well
            self.FPSBroadcast.emit(self.stream.FPS_actual)

        logger.info(f"Thread loop within frame emitter at port {self.stream.port} successfully ended")

    def stop(self):
        self.keep_collecting = False
        self.quit()

    def cv2_to_qlabel(self, frame):
        Image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        FlippedImage = cv2.flip(Image, 1)

        qt_frame = QImage(
            FlippedImage.data,
            FlippedImage.shape[1],
            FlippedImage.shape[0],
            QImage.Format.Format_RGB888,
        )
        return qt_frame

    def apply_rotation(self):
        # logger.debug("Applying Rotation")
        if self.stream.camera.rotation_count == 0:
            pass
        elif self.stream.camera.rotation_count in [1, -3]:
            self.frame = cv2.rotate(self.frame, cv2.ROTATE_90_CLOCKWISE)
        elif self.stream.camera.rotation_count in [2, -2]:
            self.frame = cv2.rotate(self.frame, cv2.ROTATE_180)
        elif self.stream.camera.rotation_count in [-1, 3]:
            self.frame = cv2.rotate(self.frame, cv2.ROTATE_90_COUNTERCLOCKWISE)



def resize_to_square(frame):

    height = frame.shape[0]
    width = frame.shape[1]

    padded_size = max(height, width)

    height_pad = int((padded_size - height) / 2)
    width_pad = int((padded_size - width) / 2)
    pad_color = [0, 0, 0]

    frame = cv2.copyMakeBorder(
        frame,
        height_pad,
        height_pad,
        width_pad,
        width_pad,
        cv2.BORDER_CONSTANT,
        value=pad_color,
    )

    return frame

if __name__ == "__main__":
    pass

    # not much to look at here... go to camera_config_dialogue.py for test