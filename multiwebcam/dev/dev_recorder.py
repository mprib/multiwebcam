import cv2
from multiwebcam.cameras.live_stream import LiveStream
from multiwebcam.cameras.camera import Camera
from queue import Queue
from multiwebcam.recording.single_video_recorder import SingleVideoRecorder
from time import sleep

from pathlib import Path

port = 0
cam = Camera(port)
cam.exposure = -7

# standard inverted charuco

q = Queue(-1)
print(f"Creating Video Stream for camera {cam.port}")
stream = LiveStream(cam, fps_target=30)
stream.subscribe(q)
stream._show_fps = True

recorder = SingleVideoRecorder(stream=stream)
destination = Path(r"C:\Users\Mac Prible\OneDrive\pyxy3d\webcamcap")

recorder.start_recording(destination)
while True:
    try:
        frame_packet = q.get()
        cv2.imshow(
            (str(port) + ": 'q' to quit"),
            frame_packet.frame,
        )

    # bad reads until connection to src established
    except AttributeError:
        pass

    key = cv2.waitKey(1)

    if key == ord("q"):
        cv2.destroyAllWindows()
        break

print("Signalling recorder to stop")
recorder.stop_recording()

while recorder.recording:
    sleep(1)
    print("waiting to finish recording")