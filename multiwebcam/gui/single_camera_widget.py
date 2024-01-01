import multiwebcam.logger

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QTabWidget,
)

from multiwebcam.gui.camera_config_dialogue import CameraConfigTab
from multiwebcam.session.session import LiveSession
logger = multiwebcam.logger.get(__name__)

class SingleCameraWidget(QWidget):
    """ 
    This is basically just the camera tabs plus the navigation bar
    """
    def __init__(self, session: LiveSession, parent=None):
        super(SingleCameraWidget, self).__init__(parent)
        self.setLayout(QVBoxLayout())    
        self.camera_tabs = CameraTabs(session)
        self.layout().addWidget(self.camera_tabs)
    
        self.session = session
    
class CameraTabs(QTabWidget):

    def __init__(self, session: LiveSession):
        super(CameraTabs, self).__init__()
        self.session = session

        self.setTabPosition(QTabWidget.TabPosition.North)
        self.add_cam_tabs()
        self.currentChanged.connect(self.on_tab_changed)
        self.on_tab_changed(0)
        self.connect_signals()
        
        
    def connect_signals(self):
        self.session.single_recording_started.connect(self.disable_tabs)
        self.session.single_recording_complete.connect(self.enable_tabs)
        
    def keyPressEvent(self, event):
        """
        Override the keyPressEvent method to allow navigation via PgUp/PgDown
        """

        if event.key() == Qt.Key.Key_PageUp:
            current_index = self.currentIndex()
            if current_index > 0:
                self.setCurrentIndex(current_index - 1)
        elif event.key() == Qt.Key.Key_PageDown:
            current_index = self.currentIndex()
            if current_index < self.count() - 1:
                self.setCurrentIndex(current_index + 1)
        else:
            super().keyPressEvent(event)
        
        
    def add_cam_tabs(self):
        tab_names = [self.tabText(i) for i in range(self.count())]
        logger.info(f"Current tabs are: {tab_names}")

        if len(self.session.streams) > 0:
            
            # construct a dict of tabs so that they can then be placed in order
            self.tab_widgets = {}
            for port, stream in self.session.streams.items():
                tab_name = f"Camera {port}"
                logger.info(f"Potentially adding {tab_name}")
                if tab_name in tab_names:
                    pass  # already here, don't bother
                else:
                    cam_tab = CameraConfigTab(self.session, port)
                    self.tab_widgets[port] = cam_tab

            # add the widgets to the tab bar in order
            ordered_ports = list(self.tab_widgets.keys())
            ordered_ports.sort()
            for port in ordered_ports:
                self.insertTab(port, self.tab_widgets[port], f"Camera {port}")
            
        else:
            logger.info("No cameras available")
    
    def on_tab_changed(self, index):
        """
        Called when the current tab changes.
        Fetches the port number from the current CameraConfigTab and calls set_active_single_stream.
        """
        # Retrieve the current CameraConfigTab instance
        current_tab = self.widget(index)

        # Ensure that the current tab is an instance of CameraConfigTab and has the port attribute
        if isinstance(current_tab, CameraConfigTab) and hasattr(current_tab, 'port'):
            port = current_tab.port
            # Call the session method with the port number
            self.session.set_active_single_stream(port) 
            
    def enable_tabs(self):
        for index in range(self.count()):
            if index != self.currentIndex():
                self.setTabEnabled(index, True)
 
    def disable_tabs(self):
        for index in range(self.count()):
            if index != self.currentIndex():
                self.setTabEnabled(index, False)
         
if __name__ == "__main__":
    from multiwebcam.configurator import Configurator
    from pathlib import Path
    from PySide6.QtWidgets import QApplication
    from multiwebcam.session.session import SessionMode
    config = Configurator(Path(r"C:\Users\Mac Prible\OneDrive\pyxy3d\webcamcap"))
    session = LiveSession(config)
    # session.load_stream_tools()
    session.set_mode(SessionMode.SingleCamera)
    session.set_active_single_stream(0)

    qapp = QApplication()
    int_calib_widget = SingleCameraWidget(session)

    int_calib_widget.show()
    qapp.exec()
        