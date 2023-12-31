from time import sleep
from threading import Event
import numpy as np

import cv2
from PySide6.QtCore import Signal, QThread
from PySide6.QtGui import QImage

from multiwebcam.cameras.synchronizer import Synchronizer
from multiwebcam.interface import FramePacket
import multiwebcam.logger

logger = multiwebcam.logger.get(__name__)

class FrameDictionaryEmitter(QThread):
    ThumbnailImagesBroadcast = Signal(dict)
    dropped_fps = Signal(dict)

    def __init__(self, synchronizer: Synchronizer, render_fps,  single_frame_height=300):
        super(FrameDictionaryEmitter, self).__init__()
        self.single_frame_height = single_frame_height
        self.synchronizer = synchronizer
        self.render_fps = render_fps
        logger.info("Initiated recording frame emitter")
        self.keep_collecting = Event()
        self.start()

    def update_render_fps(self,fps):
        self.render_fps = fps 
    def run(self):
        self.keep_collecting.set()

        while self.keep_collecting.is_set():
            sleep(1 / self.render_fps)
            logger.debug("About to get next recording frame")
            # recording_frame = self.unpaired_frame_builder.get_recording_frame()

            logger.debug("Referencing current sync packet in synchronizer")
            self.current_sync_packet = self.synchronizer.current_sync_packet

            thumbnail_qimage = {}
            for port in self.synchronizer.ports:
                frame_packet = self.current_sync_packet.frame_packets[port]
                rotation_count = self.synchronizer.streams[port].camera.rotation_count

                text_frame = frame_packet_2_thumbnail(
                    frame_packet, rotation_count, self.single_frame_height, port
                )
                q_image = cv2_to_qimage(text_frame)
                thumbnail_qimage[str(port)] = q_image

            self.ThumbnailImagesBroadcast.emit(thumbnail_qimage)

            dropped_fps_dict = {
                str(port): dropped
                for port, dropped in self.synchronizer.dropped_fps.items()
            }
            self.dropped_fps.emit(dropped_fps_dict)
        logger.info("Recording thumbnail emitter run thread ended...")


def frame_packet_2_thumbnail(
    frame_packet: FramePacket, rotation_count: int, edge_length: int, port: int
):
    raw_frame = get_frame_or_blank(frame_packet, edge_length)
    # port = frame_packet.port

    # raw_frame = self.get_frame_or_blank(None)
    square_frame = resize_to_square(raw_frame, edge_length)
    rotated_frame = apply_rotation(square_frame, rotation_count)
    flipped_frame = cv2.flip(rotated_frame, 1)

    # put the port number on the top of the frame
    text_frame = cv2.putText(
        flipped_frame,
        str(port),
        (int(flipped_frame.shape[1] / 2), int(edge_length / 4)),
        fontFace=cv2.FONT_HERSHEY_SIMPLEX,
        fontScale=1,
        color=(0, 0, 255),
        thickness=2,
    )

    return text_frame


def get_frame_or_blank(frame_packet, edge_length):
    """Synchronization issues can lead to some frames being None among
    the synched frames, so plug that with a blank frame"""

    if frame_packet is None:
        logger.debug("plugging blank frame data")
        frame = np.zeros((edge_length, edge_length, 3), dtype=np.uint8)
    else:
        frame = frame_packet.frame

    return frame


def resize_to_square(frame, edge_length):
    """To make sure that frames align well, scale them all to thumbnails
    squares with black borders."""
    logger.debug("resizing square")

    height = frame.shape[0]
    width = frame.shape[1]

    padded_size = max(height, width)

    height_pad = int((padded_size - height) / 2)
    width_pad = int((padded_size - width) / 2)
    pad_color = [0, 0, 0]

    logger.debug("about to pad border")
    frame = cv2.copyMakeBorder(
        frame,
        height_pad,
        height_pad,
        width_pad,
        width_pad,
        cv2.BORDER_CONSTANT,
        value=pad_color,
    )

    frame = resize(frame, new_height=edge_length)
    return frame


def resize(image, new_height):
    (current_height, current_width) = image.shape[:2]
    ratio = new_height / float(current_height)
    dim = (int(current_width * ratio), new_height)
    resized = cv2.resize(image, dim, interpolation=cv2.INTER_AREA)
    return resized


def apply_rotation(frame, rotation_count):
    if rotation_count == 0:
        pass
    elif rotation_count in [1, -3]:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif rotation_count in [2, -2]:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif rotation_count in [-1, 3]:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

    return frame


def prep_img_for_qpixmap(image: np.ndarray):
    """
    qpixmap needs dimensions divisible by 4 and without that weird things happen.
    """
    if image.shape[1] % 4 != 0:  # If the width of the row isn't divisible by 4
        padding_width = 4 - (image.shape[1] % 4)  # Calculate how much padding is needed
        padding = np.zeros(
            (image.shape[0], padding_width, image.shape[2]), dtype=image.dtype
        )  # Create a black image of the required size
        image = np.hstack([image, padding])  # Add the padding to the right of the image

    return image



def cv2_to_qimage(frame):
    image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    qt_frame = QImage(
        image.data,
        image.shape[1],
        image.shape[0],
        QImage.Format.Format_RGB888,
    )

    return qt_frame



