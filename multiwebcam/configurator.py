# %%

import multiwebcam.logger

from pathlib import Path
from datetime import datetime
from os.path import exists
import rtoml

from multiwebcam.cameras.camera import Camera, CAMERA_BACKENDS
from concurrent.futures import ThreadPoolExecutor

logger = multiwebcam.logger.get(__name__)


class Configurator:
    """
    A factory to provide pre-configured objects and to save the configuration
    of currently existing objects.
    """

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path
        self.config_toml_path = Path(self.workspace_path, "recording_config.toml")

        if exists(self.config_toml_path):
            self.refresh_config_from_toml()
            # this check only included for interfacing with historical tests...
            # if underlying tests data updated, this should be removed
            if "camera_count" not in self.dict.keys():
                self.dict["camera_count"] = 0
        else:
            logger.info(
                "No existing recording_config.toml found; creating starter file with charuco"
            )

            self.dict = rtoml.loads("")
            self.dict["CreationDate"] = datetime.now()
            self.dict["fps"] = 24
            self.dict["multicam_render_fps"] = 6

            self.update_config_toml()


    def save_camera_count(self, count):
        self.camera_count = count
        self.dict["camera_count"] = count
        self.update_config_toml()

    def get_camera_count(self):
        return self.dict["camera_count"]

    def get_multicam_render_fps(self):
        return self.dict["multicam_render_fps"]

    def save_multicam_render_fps(self,fps):
        self.dict["multicam_render_fps"] = fps
        self.update_config_toml()

    def get_fps_target(self):
        return self.dict["fps"]


    def save_fps(self,fps_target):
        self.dict["fps"] = fps_target
        self.update_config_toml()
        

    def refresh_config_from_toml(self):
        logger.info("Populating config dictionary with config.toml data")
        # with open(self.config_toml_path, "r") as f:
        self.dict = rtoml.load(self.config_toml_path)


    def update_config_toml(self):
        # alphabetize by key to maintain standardized layout
        sorted_dict = {key: value for key, value in sorted(self.dict.items())}
        self.dict = sorted_dict

        with open(self.config_toml_path, "w") as f:
            rtoml.dump(self.dict, f)

    def save_camera(self, camera: Camera):

        params = {
            "port": camera.port,
            "size": camera.size,
            "exposure": camera.exposure,
            "rotation_count": camera.rotation_count,
            "ignore": camera.ignore,
            "verified_resolutions": camera.verified_resolutions,
            "backend": camera.backend
        }

        self.dict["cam_" + str(camera.port)] = params
        self.update_config_toml()


    def get_cameras(self) -> dict[int, Camera]:
        cameras = {}

        def add_preconfigured_cam(params:dict):
            # try:
            port = params["port"]
            logger.info(f"Attempting to add pre-configured camera at port {port}")

            if params["ignore"]:
                logger.info(f"Ignoring camera at port {port}")
                pass  # don't load it in
            else:
                verified_resolutions = params["verified_resolutions"]
                backend = params["backend"]

                camera = Camera(port=port, verified_resolutions=verified_resolutions, backend=backend)
                camera.rotation_count = params["rotation_count"]
                camera.exposure = params["exposure"]
                cameras[port] = camera 
                
        with ThreadPoolExecutor() as executor:
            for key, params in self.dict.items():
                if key.startswith("cam"):
                    logger.info(f"Beginning to load {key} with params {params}")
                    executor.submit(add_preconfigured_cam, params)

        return cameras


if __name__ == "__main__":
    import rtoml
    from multiwebcam import __app_dir__

    app_settings = rtoml.load(Path(__app_dir__, "settings.toml"))
    recent_projects: list = app_settings["recent_projects"]

    recent_project_count = len(recent_projects)
    session_path = Path(recent_projects[recent_project_count - 1])

    config = Configurator(session_path)

# %%
