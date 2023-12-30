# Environment for managing all created objects and the primary interface for the GUI.
import multiwebcam.logger

from PySide6.QtCore import QObject, Signal
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep
from enum import Enum
from queue import Queue

from multiwebcam.cameras.camera import Camera
from multiwebcam.cameras.synchronizer import Synchronizer
from multiwebcam.gui.frame_emitter import FrameEmitter
from multiwebcam.configurator import Configurator
from multiwebcam.cameras.live_stream import LiveStream
from multiwebcam.recording.video_recorder import SyncVideoRecorder

logger = multiwebcam.logger.get(__name__)

# %%
MAX_CAMERA_PORT_CHECK = 10
FILTERED_FRACTION = 0.025  # by default, 2.5% of image points with highest reprojection error are filtered out during calibration


class SessionMode(Enum):
    """ """

    SingleCamera = "&Single Camera"
    MultiCamera = "&MultiCamera"


class QtSignaler(QObject):
    stream_tools_loaded_signal = Signal()
    stream_tools_disconnected_signal = Signal()
    recording_complete_signal = Signal()
    mode_change_success = Signal()
    fps_target_updated = Signal()

    def __init__(self) -> None:
        super(QtSignaler, self).__init__()


class LiveSession:
    def __init__(self, config: Configurator):
        # need a way to let the GUI know when certain actions have been completed
        self.qt_signaler = QtSignaler()

        self.config = config
        self.path = self.config.workspace_path

        # dictionaries of streaming related objects. key = port
        self.cameras = {}
        self.streams = {}
        self.frame_emitters = {}

        self.stream_tools_in_process = False
        self.stream_tools_loaded = False

        # load fps for various modes
        self.fps_target = self.config.get_fps_target()
        self.is_recording = False

        self.mode = None  # default mode of session

    def disconnect_cameras(self):
        """
        Shut down the streams, close the camera captures and delete the monocalibrators and synchronizer
        """
        for port, stream in self.streams.items():
            stream.stop_event.set()
        self.streams = {}
        for port, cam in self.cameras.items():
            cam.disconnect()
        self.cameras = {}
        self.synchronizer.stop_event.set()
        self.synchronizer = None
        self.stream_tools_loaded = False
        self.qt_signaler.stream_tools_disconnected_signal.emit()

    def is_camera_setup_eligible(self):
        # assume true and prove false
        eligible = True

        if len(self.cameras) == 0:
            eligible = False

        return eligible


    def set_mode(self, mode: SessionMode):
        """
        Via this method, the frame reading behavior will be changed by the GUI. If some properties are
        not available (i.e. synchronizer) they will be created
        """
        logger.info(f"Initiating switch to mode: {mode.value}")
        self.mode = mode

        match self.mode:

            case SessionMode.SingleCamera:
                # update in case something has changed

                if not self.stream_tools_loaded:
                    self.load_stream_tools()
                self.synchronizer.unsubscribe_from_streams()
                self.subscribe_all_frame_emitters()
                
            case SessionMode.MultiCamera:
                logger.info("Attempting to set recording mode")
                if not self.stream_tools_loaded:
                    logger.info("Stream tools not loaded, so loading them up...")
                    self.load_stream_tools()

                logger.info(
                    "Subscribe synchronizer to streams so video recorder can manage"
                )
                self.unsubscribe_all_frame_emitters()
                self.synchronizer.subscribe_to_streams()
                

        self.qt_signaler.mode_change_success.emit()

    def set_fps(self, fps_target: int):
        self.fps_target = fps_target
        logger.info( f"Updating streams fps to {fps_target} ")
        for stream in self.streams.values():
            stream.set_fps_target(fps_target)
        self.config.save_fps(fps_target)
        
        # signal to all camera config dialogues to update their fps target spin boxes
        self.qt_signaler.fps_target_updated.emit()


    def get_configured_camera_count(self):
        count = 0
        for key, params in self.config.dict.copy().items():
            if key.startswith("cam"):
                count += 1
        return count

    def _find_cameras(self):
        """
        Called by load_streams in the event that no cameras are returned by the configurator...
        Will populate self.cameras using multiple threads
        """

        def add_cam(port):
            try:
                logger.info(f"Trying port {port}")
                cam = Camera(port)
                logger.info(f"Success at port {port}")
                self.cameras[port] = cam
                self.config.save_camera(cam)
                logger.info( f"Loading stream at port {port}")
                self.streams[port] = LiveStream(cam)
            except:
                logger.warn(f"No camera at port {port}")

        with ThreadPoolExecutor() as executor:
            for i in range(0, MAX_CAMERA_PORT_CHECK):
                if i in self.cameras.keys():
                    # don't try to connect to an already connected camera
                    pass
                else:
                    executor.submit(add_cam, i)

        # remove potential stereocalibration data to start fresh
        for key in self.config.dict.copy().keys():
            if key.startswith("stereo"):
                del self.config.dict[key]

    def load_stream_tools(self):
        """
        Connects to stored cameras and creates streams
        Because these streams are available, the synchronizer can then be initialized
        Frame emitters are created for the individual views.

        """
        self.stream_tools_in_process = True
        # don't bother loading cameras until you load the streams
        self.cameras = self.config.get_cameras()

        if len(self.cameras) == 0:
            self._find_cameras()

        for port, cam in self.cameras.items():
            if port in self.streams.keys():
                pass  # only add if not added yet
            else:
                logger.info(f"Loading Stream for port {port}")
                stream = LiveStream(cam)
                self.streams[port] = stream
                pixmap_edge_length = 500
                frame_emitter = FrameEmitter(stream, pixmap_edge_length=pixmap_edge_length)
                self.frame_emitters[port] = frame_emitter


        self._adjust_resolutions()
    
        self.synchronizer = Synchronizer(
            self.streams
        )  # defaults to stream default fps of 6

        # recording widget becomes available when synchronizer is created
        
        self.stream_tools_loaded = True
        self.stream_tools_in_process = False

        logger.info("defaulting into multicamera mode at launch")
        self.set_mode(SessionMode.MultiCamera)

        logger.info("Signalling successful loading of stream tools")
        self.qt_signaler.stream_tools_loaded_signal.emit()

    def unsubscribe_all_frame_emitters(self):
        for emitter in self.frame_emitters.values():
            emitter.unsubscribe()
        
    def subscribe_all_frame_emitters(self):
        for emitter in self.frame_emitters.values():
            emitter.subscribe()

    def start_synchronized_recording(
        self, destination_directory: Path, store_point_history: bool = False
    ):
        logger.info("Initiating recording...")
        destination_directory.mkdir(parents=True, exist_ok=True)

        self.sync_video_recorder = SyncVideoRecorder(self.synchronizer)
        self.sync_video_recorder.start_recording(
            destination_directory, store_point_history=store_point_history
        )
        self.is_recording = True

    def stop_synchronized_recording(self):
        logger.info("Stopping recording...")
        self.sync_video_recorder.stop_recording()
        while self.sync_video_recorder.recording:
            logger.info("Waiting for video recorder to save out data...")
            sleep(0.5)

        self.is_recording = False

        logger.info("Recording of frames is complete...signalling change in status")
        self.qt_signaler.recording_complete_signal.emit()


    def _adjust_resolutions(self):
        """Changes the camera resolution to the value in the configuration, as
        log as it is not configured for the default resolution"""

        def adjust_res_worker(port):
            stream = self.streams[port]
            size = self.config.dict[f"cam_{port}"]["size"]
            default_size = self.cameras[port].default_resolution

            if size[0] != default_size[0] or size[1] != default_size[1]:
                logger.info(
                    f"Beginning to change resolution at port {port} from {default_size[0:2]} to {size[0:2]}"
                )
                stream.change_resolution(size)
                logger.info(
                    f"Completed change of resolution at port {port} from {default_size[0:2]} to {size[0:2]}"
                )

        with ThreadPoolExecutor() as executor:
            for port in self.cameras.keys():
                executor.submit(adjust_res_worker, port)

# %%

# %%

# %%
