"""Entry point for multiwebcam application.

Usage:
    multiwebcam    # or 'mwc' for short
    python -m multiwebcam

Launches the application using the current directory as the project path.
If multiwebcam.toml exists, loads camera profiles from it.
If not, creates it when cameras are discovered.
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from multiwebcam.ui import MainWindow


def main() -> None:
    """Launch multiwebcam application.

    Uses current working directory as project path.
    """
    app = QApplication(sys.argv)

    # Use current directory as project path
    project_path = Path.cwd()

    # Log what we're doing
    toml_path = project_path / "multiwebcam.toml"
    if toml_path.exists():
        print(f"Loading project from: {project_path}")
    else:
        print(f"New project in: {project_path}")
        print("  Camera profiles will be saved to multiwebcam.toml")

    window = MainWindow(project_path)
    window.setWindowTitle(f"multiwebcam - {project_path.name}")
    window.resize(1200, 800)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
