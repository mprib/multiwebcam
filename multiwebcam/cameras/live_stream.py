# This widget is the primary functional unit of the motion capture. It
# establishes the connection with the video source and manages the thread
# that reads in frames.


import multiwebcam.logger

from time import perf_counter, sleep
from queue import Queue
from threading import Thread, Event

import cv2
import numpy as np

from multiwebcam.cameras.camera import Camera
from multiwebcam.interface import FramePacket

logger = multiwebcam.logger.get(__name__)

class LiveStream():
    def __init__(self, camera: Camera, fps_target: int = 6):
        self.camera: Camera = camera
        self.port = camera.port

        self.stop_event = Event()

        # list of queues that will have frame packets pushed to them
        self.subscribers = []

        # make sure camera no longer reading before trying to change resolution
        self.stop_confirm = Queue()

        self._show_fps = False  # used for testing


        self.set_fps_target(fps_target)
        self.FPS_actual = 0
        # Start the thread to read frames from the video stream
        self.thread = Thread(target=self._play_worker, args=(), daemon=True)
        self.thread.start()

        # initialize time trackers for actual FPS determination
        self.frame_time = perf_counter()
        self.avg_delta_time = 1  # initialize to something to avoid errors elsewhere

    @property
    def size(self):
        # because the camera resolution will potentially change after stream initialization, this should be 
        # read directly from the camera whenever a caller (e.g. videorecorder) wants the current resolution
        return self.camera.size

    def subscribe(self, queue: Queue):
        if queue not in self.subscribers:
            logger.info(f"Adding queue to subscribers at stream {self.port}")
            self.subscribers.append(queue)
            logger.info(f"...now {len(self.subscribers)} subscriber(s) at {self.port}")
        else:
            logger.warn(
                f"Attempted to subscribe to live stream at port {self.port} twice"
            )

    def unsubscribe(self, queue: Queue):
        try:
            if queue in self.subscribers:
                logger.info(f"Removing subscriber from queue at port {self.port}")
                self.subscribers.remove(queue)
                logger.info(
                    f"{len(self.subscribers)} subscriber(s) remain at port {self.port}"
                )
            else:
                logger.warn(
                    f"Attempted to unsubscribe to live stream that was not subscribed to\
                    at port {self.port} twice"
                )
        except:
            logger.warn("Attempted to remove queue that may have been removed twice at once")

    def set_fps_target(self, fps_target):
        """
        This is done through a method as it will also do a one-time determination of the times as which
        frames should be read (the milestones)
        """

        self.fps_target = fps_target
        milestones = []
        for i in range(0, fps_target):
            milestones.append(i / fps_target)
        logger.info(f"Setting fps to {self.fps_target} at port {self.port}")
        self.milestones = np.array(milestones)

    def wait_to_next_frame(self):
        """
        based on the next milestone time, return the time needed to sleep so that
        a frame read immediately after would occur when needed
        """

        time = perf_counter()
        fractional_time = time % 1
        all_wait_times = self.milestones - fractional_time
        future_wait_times = all_wait_times[all_wait_times > 0]

        if len(future_wait_times) == 0:
            return 1 - fractional_time
        else:
            return future_wait_times[0]

    def get_FPS_actual(self):
        """
        set the actual frame rate; called within roll_camera()
        needs to be called from within roll_camera to actually work
        Note that this is a smoothed running average
        """
        self.delta_time = perf_counter() - self.start_time
        self.start_time = perf_counter()
        if not self.avg_delta_time:
            self.avg_delta_time = self.delta_time

        # folding in current frame rate to trailing average to smooth out
        self.avg_delta_time = 0.5 * self.avg_delta_time + 0.5 * self.delta_time
        self.previous_time = self.start_time
        return 1 / self.avg_delta_time

    def _play_worker(self):
        """
        Worker function that is spun up by Thread. Reads in a working frame,
        calls various frame processing methods on it, and updates the exposed
        frame
        """
        self.frame_index = 0
        self.start_time = perf_counter()  # used to get initial delta_t for FPS
        first_time = True
        while not self.stop_event.is_set():
            if first_time:
                logger.info(f"Camera now rolling at port {self.port}")
                first_time = False

            if self.camera.capture.isOpened():
                # slow wait if not pushing frames
                # this is a sub-optimal busy wait spin lock, but it works and I'm tired.
                # stop_event condition added to allow loop to wrap up
                # if attempting to change resolution
                spinlock_looped = False
                while len(self.subscribers) == 0 and not self.stop_event.is_set():
                    if not spinlock_looped:
                        logger.info(f"Spinlock initiated at port {self.port}")
                        spinlock_looped = True
                    sleep(0.5)
                if spinlock_looped == True:
                    logger.info(f"Spinlock released at port {self.port}")

                # Wait an appropriate amount of time to hit the frame rate target
                sleep(self.wait_to_next_frame())

                read_start = perf_counter()
                grab_success = self.camera.capture.grab()
                self.success, self.frame = self.camera.capture.retrieve()

                read_stop = perf_counter()
                self.frame_time = (read_start + read_stop) / 2

                if self.success and len(self.subscribers) > 0:
                    # logger.info(f"Pushing frame to reel at port {self.port}")

                    if self._show_fps:
                        self._add_fps()

                    # Rate of calling recalc must be frequency of this loop

                    self.FPS_actual = self.get_FPS_actual()
                    frame_packet = FramePacket(
                        port=self.port,
                        frame_time=self.frame_time,
                        frame_index= self.frame_index,
                        frame=self.frame,
                        fps = self.FPS_actual
                    )

                    # cv2.imshow(str(self.port), frame_packet.frame_with_points)
                    # key = cv2.waitKey(1)
                    # if key == ord("q"):
                    #     cv2.destroyAllWindows()
                    #     break

                    for q in self.subscribers:
                        q.put(frame_packet)

                self.frame_index +=1

        logger.info(f"Stream stopped at port {self.port}")
        self.stop_event.clear()
        self.stop_confirm.put("Successful Stop")

    def change_resolution(self, res):
        logger.info(f"About to stop camera at port {self.port}")
        self.stop_event.set()
        self.stop_confirm.get()
        logger.info(f"Roll camera stop confirmed at port {self.port}")

        self.FPS_actual = 0
        self.avg_delta_time = None

        # reconnecting a few times without disconnnect sometimes crashed python
        logger.info(f"Disconnecting from port {self.port}")
        self.camera.disconnect()
        logger.info(f"Reconnecting to port {self.port}")
        self.camera.connect()

        self.camera.size = res
        # Spin up the thread again now that resolution is changed
        logger.info(
            f"Beginning roll_camera thread at port {self.port} with resolution {res}"
        )
        self.thread = Thread(target=self._play_worker, args=(), daemon=True)
        self.thread.start()

    def _add_fps(self):
        """NOTE: this is used in F5 test, not in external use"""
        self.fps_text = str(int(round(self.FPS_actual, 0)))
        cv2.putText(
            self.frame,
            "FPS:" + self.fps_text,
            (10, 70),
            cv2.FONT_HERSHEY_PLAIN,
            2,
            (0, 0, 255),
            3,
        )


if __name__ == "__main__":
    ports = [0]
    # ports = [3]

    cams = []
    for port in ports:
        print(f"Creating camera {port}")
        cam = Camera(port)
        cam.exposure = -7
        cams.append(cam)

    # standard inverted charuco
    frame_packet_queues = {}

    streams = []
    for cam in cams:
        q = Queue(-1)
        frame_packet_queues[cam.port] = q

        print(f"Creating Video Stream for camera {cam.port}")
        stream = LiveStream(cam, fps_target=30)
        stream.subscribe(frame_packet_queues[cam.port])
        stream._show_fps = True
        streams.append(stream)

    while True:
        try:
            for port in ports:
                frame_packet = frame_packet_queues[port].get()

                cv2.imshow(
                    (str(port) + ": 'q' to quit"),
                    frame_packet.frame,
                )

        # bad reads until connection to src established
        except AttributeError:
            pass

        key = cv2.waitKey(1)

        if key == ord("q"):
            for stream in streams:
                stream.camera.capture.release()
            cv2.destroyAllWindows()
            exit(0)

        if key == ord("v"):
            for stream in streams:
                print(f"Attempting to change resolution at port {stream.port}")
                stream.change_resolution((640, 480))

        if key == ord("s"):
            for stream in streams:
                stream.stop()
            cv2.destroyAllWindows()
            exit(0)
