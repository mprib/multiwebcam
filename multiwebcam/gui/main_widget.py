import multiwebcam.logger
from pathlib import Path


import subprocess
import os
from threading import Thread
import sys
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QWidget,
    QDockWidget,
    QMenu,
)
import rtoml
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import Qt
from multiwebcam import __root__, __settings_path__
from multiwebcam.session.session import LiveSession, SessionMode
from multiwebcam.gui.log_widget import LogWidget
from multiwebcam.configurator import Configurator
from multiwebcam.gui.single_camera_widget import (
    SingleCameraWidget,
)
from multiwebcam.gui.perf_counter_widget import PerfCounterWidget
from multiwebcam.gui.multicamera_widget import MultiCameraWidget

logger = multiwebcam.logger.get(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        self.app_settings = rtoml.load(__settings_path__)

        # Persistent parent widget
        self.persistent_parent = QWidget(self)

        self.setWindowTitle("multiwebcam")
        self.setWindowIcon(
            QIcon(str(Path(__root__, "multiwebcam/gui/icons/tri-cam.svg")))
        )
        self.setMinimumSize(500, 500)

        # File Menu
        self.menu = self.menuBar()

        # CREATE FILE MENU
        self.file_menu = self.menu.addMenu("&File")
        self.open_project_action = QAction("New/Open Project", self)
        self.file_menu.addAction(self.open_project_action)

        # Open Recent
        self.open_recent_project_submenu = QMenu("Recent Projects...", self)
        # Populate the submenu with recent project paths;
        # reverse so that last one appended is at the top of the list
        for project_path in reversed(self.app_settings["recent_projects"]):
            self.add_to_recent_project(project_path)

        self.file_menu.addMenu(self.open_recent_project_submenu)
        self.open_project_dir_action = QAction("Open Project Directory")
        self.file_menu.addAction(self.open_project_dir_action)
        self.open_project_dir_action.setEnabled(False)

        self.exit_multiwebcam_action = QAction("Exit", self)
        self.file_menu.addAction(self.exit_multiwebcam_action)

        # CREATE MODE MENU
        self.mode_menu = self.menu.addMenu("&Mode")
        self.intrinsic_mode_select = QAction(SessionMode.SingleCamera.value)
        self.recording_mode_select = QAction(SessionMode.MultiCamera.value)
        self.mode_menu.addAction(self.intrinsic_mode_select)
        self.mode_menu.addAction(self.recording_mode_select)

        for action in self.mode_menu.actions():
            action.setEnabled(False)

        self.connect_menu_actions()
        self.blank_widget = QWidget()
        self.setCentralWidget(self.blank_widget)

        # create log window which is fixed below main window
        self.docked_logger = QDockWidget("Log", self)

        # Add DockWidgetClosable feature
        self.docked_logger.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.docked_logger.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)

        self.log_widget = LogWidget()
        self.docked_logger.setWidget(self.log_widget)

        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.docked_logger)

    def connect_menu_actions(self):
        self.open_project_action.triggered.connect(self.create_new_project_folder)
        # self.connect_cameras_action.triggered.connect(self.load_stream_tools)
        self.exit_multiwebcam_action.triggered.connect(QApplication.instance().quit)
        # self.disconnect_cameras_action.triggered.connect(self.disconnect_cameras)

        for action in self.mode_menu.actions():
            action.triggered.connect(self.mode_change_action)

        self.open_project_dir_action.triggered.connect(self.open_project_dir)

    def open_project_dir(self):
        if not os.path.isdir(self.workspace_dir):
            raise ValueError(f"The path {self.workspace_dir} is not a valid directory")

        if sys.platform.startswith("win32"):
            subprocess.run(["explorer", self.workspace_dir])
        elif sys.platform.startswith("darwin"):
            subprocess.run(["open", self.workspace_dir])
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", self.workspace_dir])
        else:
            raise OSError("Unsupported operating system")

    def mode_change_action(self):
        action = self.sender()

        # create a reverse lookup dictionary to pull the mode enum that should be activated
        SessionModeLookup = {mode.value: mode for mode in SessionMode}
        mode = SessionModeLookup[action.text()]
        logger.info(f"Attempting to set session mode to {mode.value}")
        self.session.set_mode(mode)
        logger.info(f"Successful change to {mode} Mode")

    def update_central_widget_mode(self):
        """
        This will be triggered whenever the session successfully completes a mode change and emits
        a signal to that effect.
        """
        
        self.open_project_dir_action.setEnabled(True)
        logger.info("Begin process of updating central widget")
        logger.info(f"Matching next tab to active session mode: {self.session.mode}")
        # Create the new central widget based on the mode
        match self.session.mode:
            case SessionMode.SingleCamera:
                self.single_camera_widget = SingleCameraWidget(
                    self.session, parent=self.persistent_parent
                )
                logger.info("Setting camera setup widget to central widget")
                self.setCentralWidget(self.single_camera_widget)
            case SessionMode.MultiCamera:
                logger.info("Setting multirecording widget to central widget")
                self.multicamera_widget = MultiCameraWidget(
                    self.session, parent=self.persistent_parent
                )
                logger.info("Setting multirecording widget to central widget")
                self.setCentralWidget(self.multicamera_widget)

    def update_enable_disable(self):
        # note: if the cameras are connected,then you can peak
        # into extrinsic/recording tabs, though cannot collect data

        # you can always look at a charuco board

        if self.session.is_camera_setup_eligible():
            self.intrinsic_mode_select.setEnabled(True)
            self.recording_mode_select.setEnabled(True)
        else:
            self.intrinsic_mode_select.setEnabled(False)
            self.recording_mode_select.setEnabled(False)

    def disconnect_cameras(self):
        self.setCentralWidget(QWidget())
        self.session.disconnect_cameras()
        self.disconnect_cameras_action.setEnabled(False)
        self.connect_cameras_action.setEnabled(True)
        self.update_enable_disable()

    def load_stream_tools(self):
        self.connect_cameras_action.setEnabled(False)
        self.disconnect_cameras_action.setEnabled(True)
        self.thread = Thread(
            target=self.session.load_stream_tools, args=(), daemon=True
        )
        self.thread.start()

    def launch_session(self, path_to_folder: str):
        self.workspace_dir = Path(path_to_folder)
        self.config = Configurator(self.workspace_dir)
        logger.info(
            f"Launching session with config file stored in {self.workspace_dir}"
        )
        self.session = LiveSession(self.config)
        self.session.load_stream_tools()  # defaults to multicam state
        self.connect_session_signals()  # must be connected for mode change signal to build central widget

        # now connecting to cameras is an option
        # self.connect_cameras_action.setEnabled(True)

        # but must exit and start over to launch a new session for now

        self.open_project_action.setEnabled(False)
        self.open_recent_project_submenu.setEnabled(False)
        self.update_enable_disable()

    def connect_session_signals(self):
        """
        After launching a session, connect signals and slots.
        Much of these will be from the GUI to the session and vice-versa
        """
        self.session.mode_change_success.connect(self.update_central_widget_mode)
        self.session.stream_tools_loaded_signal.connect(self.update_enable_disable)
        self.session.stream_tools_disconnected_signal.connect(
            self.update_enable_disable
        )
        self.session.mode_change_success.connect(self.update_enable_disable)

    def add_to_recent_project(self, project_path: str):
        recent_project_action = QAction(project_path, self)
        recent_project_action.triggered.connect(self.open_recent_project)
        self.open_recent_project_submenu.addAction(recent_project_action)

    def open_recent_project(self):
        action = self.sender()
        project_path = action.text()
        logger.info(f"Opening recent session stored at {project_path}")
        self.launch_session(project_path)

    def create_new_project_folder(self):
        default_folder = Path(self.app_settings["last_project_parent"])
        dialog = QFileDialog()
        path_to_folder = dialog.getExistingDirectory(
            parent=None,
            caption="Open Previous or Create New Project Directory",
            dir=str(default_folder),
            options=QFileDialog.Option.ShowDirsOnly,
        )

        if path_to_folder:
            logger.info(("Creating new project in :", path_to_folder))
            self.add_project_to_recent(path_to_folder)
            self.launch_session(path_to_folder)

    def add_project_to_recent(self, folder_path):
        if str(folder_path) in self.app_settings["recent_projects"]:
            pass
        else:
            self.app_settings["recent_projects"].append(str(folder_path))
            self.app_settings["last_project_parent"] = str(Path(folder_path).parent)
            self.update_app_settings()
            self.add_to_recent_project(folder_path)

    def update_app_settings(self):
        with open(__settings_path__, "w") as f:
            rtoml.dump(self.app_settings, f)


def launch_main(show_clock=False):
    # import qdarktheme

    app = QApplication(sys.argv)
    # qdarktheme.setup_theme("auto")
    window = MainWindow()

    if show_clock:
        widget = PerfCounterWidget()
        widget.show()

    window.show()
    app.exec()


if __name__ == "__main__":
    launch_main()
