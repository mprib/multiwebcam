


<div align="center">  

# 📷📷📷 MULTIWEBCAM 📷📷📷
  
  <img src = "https://github.com/mprib/multiwebcam/assets/31831778/73636fdb-c5a1-4f29-af7d-418a1072b0be" width = "200">

*Synchronized webcam recording to bootstrap low-cost/early-stage computer vision projects*

</div>

<div align="center">
  
[![PyPI - License](https://img.shields.io/pypi/l/multiwebcam?color=blue)](https://www.gnu.org/licenses/lgpl-3.0.en.html)
[![PyPI - Version](https://img.shields.io/pypi/v/multiwebcam?color=blue)](https://pypi.org/project/multiwebcam/)
[![GitHub last commit](https://img.shields.io/github/last-commit/mprib/multiwebcam.svg)](https://github.com/mprib/multiwebcam/commits)
![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)

</div>


# Introduction

I needed a way to record synchronized video while prototyping a computer vision project ([pyxy3D](https://github.com/mprib/pyxy3d)). Extreme temporal and spatial precision were less important than getting something reasonable with a minimal budget. When conscientiously managed, USB webcams controlled via OpenCV can perform surprisingly well at this task. I have spun this functionality off into its own package to create a clear seperation of concerns between data capture and data processing, while hopefully creating a simpler package that others might find useful. 

If MultiWebCam (MWC) is close to what you need but not quite, please feel free to raise an issue and I'll see if I can incorporate your use case. These are the core functions that are currently implemented:

- Record synchronized frames from multiple webcams
- Record from single webcams to pull single camera calibration video.
- synchronize in real time to understand dropped frame rate
- include frame-by-frame time stamp history to facilitate off-line processing
- easy adjustment of the following parameters:
  - resolution
  - exposure
  - target fps
 


# Quick Start
## Basic `pip` install

You can install MWC into your python environment with `pip install multiwebcam` and then launch it from the command line with

```bash
mwc
```

Note that this has primarily been  tested on Windows 10, infrequently on MacOS, and will not work on Linux as far as I can tell ☹️. If someone is familiar with getting USB cameras working through OpenCV on Linux, I'm all ears.



## Editable Install Using Poetry

If you prefer to contribute to MWC or want to install it in editable mode, follow these steps using Poetry:

Clone the Repository:

```bash
git clone https://github.com/mprib/multiwebcam.git
cd multiwebcam
```

Install Poetry:
```
pip install poetry
```

Set Up the Environment:

```bash
poetry install
```

By running poetry install, you'll install all dependencies and also set up the multiwebcam package in editable mode. Any changes you make to the code will be reflected in your environment.

# Capturing Data

Launch MultiWebCam from the command line:

```
mwc
```

Once you've launched MultiWebCam, choose a new project directory through the File menu. Make sure that the USB cameras you want to use are currently plugged in when you launch the new session.

MWC will attempt to connect to the cameras currently and will create a `recording_config.toml` file in the project directory. 

From the `Mode` menu you can select single camera to change camera settings (such as resolution and exposure). On the MultCamera mode you can set the target fps to achieve a desired dropped frame rate and record batches of videos.
