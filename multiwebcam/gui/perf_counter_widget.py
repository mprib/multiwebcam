import sys
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
import time

class PerfCounterWidget(QWidget):
    def __init__(self):
        super().__init__()

        # Set up the layout
        self.layout = QVBoxLayout()
        self.perfLabel = QLabel(self)
        
        font = QFont()
        font.setPointSize(100)
        self.perfLabel.setFont(font)

        self.layout.addWidget(self.perfLabel)
        self.setLayout(self.layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateLabel)
        self.timer.start(10)  # Update interval in milliseconds


    def updateLabel(self):
        # Calculate elapsed time since the start of the application
        elapsedTime = time.perf_counter()
        # Update the label with the current perf_counter value
        self.perfLabel.setText(f"{elapsedTime:.4f}")



def main():
    app = QApplication(sys.argv)
    widget = PerfCounterWidget()
    widget.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    
    main()

