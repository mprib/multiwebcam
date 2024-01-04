
<div align="center">  

# 📷📷📷 MULTIWEBCAM 📷📷📷
  
  <img src = "https://github.com/mprib/multiwebcam/assets/31831778/73636fdb-c5a1-4f29-af7d-418a1072b0be" width = "200">

*Synchronized webcam recording to bootstrap low-cost/early-stage computer vision projects*

</div>

# What it does

Records synchronized frames from multiple webcams, including frame-by-frame time stamp history, real time synchronization of frames and reporting of dropped frames. 

# Motivation

I needed a way to pull down synchronized video while prototyping a computer vision project (https://github.com/mprib/pyxy3d). Extreme temporal and spatial precision were less important than getting something reasonable with a minimal budget. 

Please note that given the size of some core dependencies (OpenCV, Mediapipe, and PySide6 are among them) installation and initial launch can take a while. 

# Quick Start
## Basic `pip` install

You can install MultiWebCam into your python environment with `pip install multiwebcam` and then launch it from the command line with

```bash
mwc
```

Note that this has primarily been  tested on Windows 10, infrequently on MacOS, and will not work on Linux as far as I can tell ☹️. If someone is familiar with getting USB cameras working through OpenCV, I'm all ears.
