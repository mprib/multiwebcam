
from multiwebcam.cameras.camera import Camera
from multiwebcam.cameras.synchronizer import Synchronizer
from multiwebcam.cameras.live_stream import LiveStream
from queue import Queue
from multiwebcam.interface import SyncPacket

cam_0 = Camera(0, verified_resolutions=[(640,480), (1280,720)])
cam_0.size = (640,480)
cam_1 = Camera(1, verified_resolutions=[(640,480), (1280,720)])
cam_1.size = (640,480)

stream_0 = LiveStream(camera=cam_0,fps_target=6)
stream_1 = LiveStream(camera=cam_1,fps_target=6)


streams = {0:stream_0, 1:stream_1}

syncr = Synchronizer(streams=streams)
syncr.start()
sync_packet_q = Queue()
syncr.subscribe_to_sync_packets(sync_packet_q)

while True:
    
    sync_packet:SyncPacket = sync_packet_q.get()  
    
    print(sync_packet.frame_packets)