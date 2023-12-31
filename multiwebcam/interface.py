from dataclasses import dataclass
import numpy as np
from queue import Queue
from abc import ABC, abstractmethod
import cv2


# @dataclass(slots=True)
@dataclass(frozen=True, slots=True)
class FramePacket:
    """
    Holds the data for a single frame from a camera, including the frame itself,
    the frame time and the points if they were generated
    """

    port: int
    frame_index: int
    frame_time: float
    frame: np.ndarray
    fps: float

@dataclass(frozen=True, slots=True)
class SyncPacket:
    """
    SyncPacket holds syncronized frame packets.
    """

    sync_index: int
    frame_packets: dict

    @property
    def dropped(self):
        """
        convencience method to ease tracking of dropped frame rate within the synchronizer
        """
        temp_dict = {}
        for port, packet in self.frame_packets.items():
            if packet is None:
                temp_dict[port] = 1
            else:
                temp_dict[port] = 0
        return temp_dict
    
    @property
    def frame_packet_count(self):
        count = 0
        for port, packet in self.frame_packets.items():
            if packet is not None:
                 count+= 1
        return count
        
