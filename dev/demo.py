
from queue import Queue

from multiwebcam.cameras.camera import Camera
from multiwebcam.cameras.live_stream import LiveStream
from multiwebcam.cameras.synchronizer import Synchronizer
from multiwebcam.interface import SyncPacket

# create a camera...this will contain an openCV cap object
# passing in verified resolutions keeps the camera from trying to 
# figure out viable resolutions which can take a moment
# port is the same port taht openCV would assign
cam_0 = Camera(port=0, verified_resolutions=[(640,480), (1280,720)])
cam_0.size = (640,480)
cam_1 = Camera(port=1, verified_resolutions=[(640,480), (1280,720)])
cam_1.size = (640,480)


# each stream has a camera
stream_0 = LiveStream(camera=cam_0,fps_target=6)
stream_1 = LiveStream(camera=cam_1,fps_target=6)

# organize a dictionary of streams
streams = {0:stream_0, 1:stream_1}

# pass that dict to initialize the synchronizer
syncr = Synchronizer(streams=streams)

# create a queue that the synchronizer can push output to
sync_packet_q = Queue()
syncr.subscribe_to_sync_packets(sync_packet_q)

while True:
    # read off the synched frames as they become available    
    sync_packet:SyncPacket = sync_packet_q.get()  
   
    # see multiwebcam.interface.py for the general nested structure
    # of the sync packet 
    print(sync_packet.frame_packets)