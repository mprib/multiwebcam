# from PySide6.QtCore import QObject, Signal
from pathlib import Path
from queue import Queue
from threading import Thread, Event
import cv2

from multiwebcam.cameras.live_stream import LiveStream
from multiwebcam.interface import FramePacket
import multiwebcam.logger

logger = multiwebcam.logger.get(__name__)


class SingleVideoRecorder:
    def __init__(self, stream:LiveStream):
        """
        suffix: provide a way to clarify any modifications to the video that are being saved
        This is likely going to be the name of the tracker used in most cases
        """
        super().__init__()

        self.stream = stream
        self.port = self.stream.port
        self.recording = False
        self.trigger_stop = Event()
        self.frame_packet_in_q = Queue(-1)

    def save_data_worker( self ):
        # connect video recorder to synchronizer via an "in" queue
        path = str(Path(self.destination_folder, f"port_{self.port}.mp4"))
        logger.info(f"Building video writer for port {self.port}; recording to {path}")
        fourcc = cv2.VideoWriter_fourcc(*"MP4V")
        frame_size = self.stream.size
        logger.info(
            f"Creating video writer with fps of {self.stream.fps_target} and frame size of {frame_size}"
        )
        self.video_writer = cv2.VideoWriter(path, fourcc, self.stream.fps_target, frame_size)

        stream_subscription_released = False
        self.stream.subscribe(self.frame_packet_in_q)

        # this is where the issue is... need to figure out when the queue is empty...
        logger.info("Entering Save data worker loop entered")
        while self.frame_packet_in_q.qsize() > 0 or not self.trigger_stop.is_set():
            frame_packet: FramePacket = self.frame_packet_in_q.get()

            # provide periodic updates of recording queue
            # logger.info("Getting size of sync packet q")
            backlog = self.frame_packet_in_q.qsize()
            if backlog % 25 == 0 and backlog != 0:
                logger.info(
                    f"Size of unsaved frames on the recording queue is {self.frame_packet_in_q.qsize()}"
                )

            if frame_packet is None:
                # relenvant when
                logger.info("End of sync packets signaled...breaking record loop")
                break
            else:
                # logger.info("Processing frame packet...")
                self.video_writer.write(frame_packet.frame)

            if not stream_subscription_released and self.trigger_stop.is_set():
                logger.info("Save frame worker winding down...")
                self.stream.unsubscribe(self.frame_packet_in_q)
                stream_subscription_released = True

        self.video_writer.release()
        self.trigger_stop.clear()  # reset stop recording trigger
        self.recording = False


    def start_recording(
        self,
        destination_folder: Path,
    ):
        logger.info(f"All video data to be saved to {destination_folder}")

        self.destination_folder = destination_folder

        # create the folder if it doesn't already exist
        self.destination_folder.mkdir(exist_ok=True, parents=True)

        self.recording = True
        self.recording_thread = Thread(
            target=self.save_data_worker,
            args=[],
            daemon=True,
        )
        self.recording_thread.start()

    def stop_recording(self):
        logger.info("about to Stop recording initiated within VideoRecorder")
        self.trigger_stop.set()
        logger.info("Stop recording initiated within VideoRecorder")
