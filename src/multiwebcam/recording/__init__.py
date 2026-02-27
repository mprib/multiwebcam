"""Recording system for multi-camera capture."""

from multiwebcam.recording.timestamps import TimestampCollector, write_timestamps_csv
from multiwebcam.recording.recorder import FrameRecorder, RecordingResult

__all__ = [
    "FrameRecorder",
    "RecordingResult",
    "TimestampCollector",
    "write_timestamps_csv",
]
