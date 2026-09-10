import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from main_window import MainWindow


def main():
    # Enable high DPI scaling
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("Traducteur PDF Hors-Ligne")
    app.setOrganizationName("Antigravity")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
