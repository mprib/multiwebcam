"""Control panel widget for V4L2 camera controls."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)

from multiwebcam.sources.controls import V4L2Control


class ControlPanel(QWidget):
    """Dynamically builds UI controls for V4L2 camera settings.

    Creates appropriate widgets for each control type:
    - int: QSlider + QSpinBox (bidirectionally linked)
    - bool: QCheckBox
    - menu: QComboBox with menu items

    Signals:
        control_changed: Emitted when any control value changes.
                        Args: (control_name: str, value: int)
        defaults_restore_requested: Emitted when Restore Defaults button clicked.
    """

    control_changed = Signal(str, int)
    defaults_restore_requested = Signal()

    def __init__(self, controls: list[V4L2Control], parent=None):
        super().__init__(parent)
        self._controls = controls
        self._updating = False  # Guard flag to prevent signal loops

        self._build_ui()

    def _build_ui(self) -> None:
        """Construct the control panel layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create scrollable area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # Section header
        header = QLabel("Camera Controls")
        header_font = QFont()
        header_font.setBold(True)
        header.setFont(header_font)
        scroll_layout.addWidget(header)

        if not self._controls:
            # Show message for empty controls
            empty_label = QLabel("No controls available")
            empty_label.setEnabled(False)
            scroll_layout.addWidget(empty_label)
        else:
            # Build form with controls
            form_layout = QFormLayout()
            scroll_layout.addLayout(form_layout)

            for control in self._controls:
                label_text = self._format_label(control.name)
                widget = self._create_control_widget(control)
                if widget:
                    form_layout.addRow(label_text, widget)

            # Add Restore Defaults button
            restore_btn = QPushButton("Restore Defaults")
            restore_btn.clicked.connect(self.defaults_restore_requested.emit)
            scroll_layout.addWidget(restore_btn)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)

    def _format_label(self, control_name: str) -> str:
        """Convert control name to readable label.

        Example: "exposure_absolute" -> "Exposure Absolute"
        """
        return control_name.replace("_", " ").title()

    def _create_control_widget(self, control: V4L2Control) -> QWidget | None:
        """Create appropriate widget for control type."""
        if control.type == "int":
            return self._create_int_control(control)
        elif control.type == "bool":
            return self._create_bool_control(control)
        elif control.type == "menu":
            return self._create_menu_control(control)
        return None

    def _create_int_control(self, control: V4L2Control) -> QWidget:
        """Create slider + spinbox pair for integer control."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # Slider
        slider = QSlider()
        slider.setOrientation(Qt.Orientation.Horizontal)
        slider.setMinimum(control.min or 0)
        slider.setMaximum(control.max or 100)
        if control.step:
            slider.setSingleStep(control.step)
        if control.current is not None:
            slider.setValue(control.current)

        # Spinbox
        spinbox = QSpinBox()
        spinbox.setMinimum(control.min or 0)
        spinbox.setMaximum(control.max or 100)
        if control.step:
            spinbox.setSingleStep(control.step)
        if control.current is not None:
            spinbox.setValue(control.current)

        # Connect slider <-> spinbox bidirectionally
        # Use lambda to capture control name and guard against signal loops
        def on_slider_change(value: int) -> None:
            if not self._updating:
                self._updating = True
                spinbox.setValue(value)
                self.control_changed.emit(control.name, value)
                self._updating = False

        def on_spinbox_change(value: int) -> None:
            if not self._updating:
                self._updating = True
                slider.setValue(value)
                self.control_changed.emit(control.name, value)
                self._updating = False

        slider.valueChanged.connect(on_slider_change)
        spinbox.valueChanged.connect(on_spinbox_change)

        layout.addWidget(slider, stretch=3)
        layout.addWidget(spinbox, stretch=1)

        return container

    def _create_bool_control(self, control: V4L2Control) -> QWidget:
        """Create checkbox for boolean control."""
        checkbox = QCheckBox()
        checkbox.setChecked(control.current != 0 if control.current is not None else False)

        # Connect to control_changed signal
        checkbox.stateChanged.connect(
            lambda state: self.control_changed.emit(control.name, 1 if state else 0)
        )

        return checkbox

    def _create_menu_control(self, control: V4L2Control) -> QWidget:
        """Create combobox for menu control."""
        combo = QComboBox()

        if control.menu_items:
            # Populate combo with menu items
            # Store int key as user data, display label text
            for key in sorted(control.menu_items.keys()):
                label = control.menu_items[key]
                combo.addItem(label, userData=key)

            # Set current selection if available
            if control.current is not None:
                index = combo.findData(control.current)
                if index >= 0:
                    combo.setCurrentIndex(index)

        # Connect to control_changed signal
        # userData holds the int key
        combo.currentIndexChanged.connect(
            lambda: self.control_changed.emit(control.name, combo.currentData())
        )

        return combo
